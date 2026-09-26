#!/usr/bin/env python3

import vlc
import sys
import atexit
import threading
import os
import json
import time
import random
import mqtt_client
from time import sleep
from pathlib import Path
from shared.vlc_helper import (
    log,
    playlist_updater,
    stop_playlist_thread,
    update_playlist_timestamp_on_startup,
    get_selected_video,
    get_secondary_video_mode,
    read_pause_flag,
    write_pause_flag,
    is_schedule_enabled_now,
    is_current_schedule_active,
    get_current_scheduler_category
)

HOME = Path(os.path.expanduser("~"))
LOG_FOLDER = HOME / "logs"
VIDEO_FOLDER = HOME / "videos"
PAUSE_VIDEO = HOME / "pause_video" / "paused_rotated.mp4"
LOG_FOLDER.mkdir(parents=True, exist_ok=True)
player = None
instance = None
scheduled_play_timer = None
scheduled_play_lock = threading.Lock()
playback_lock = threading.Lock()
current_sync_tag = None
current_sync_id = None
current_sync_path = None
current_playback_path = None


def load_and_pause(media_path):
    media = instance.media_new(media_path)
    player.set_media(media)
    player.play()
    sleep(0.5)
    player.set_pause(1)
    player.set_time(0)


def prepare_media_for_sync(media_path):
    with playback_lock:
        load_and_pause(media_path)


# ============================================================
# Trigger Change
# ============================================================

def change_video_on_trigger():
    try:
        with open(HOME / "settings.json", "r") as f:
            settings = json.load(f)
    except Exception as e:
        log(f"Failed to load settings for Trigger Change: {e}", "ERROR")
        return get_selected_video()

    playlist = settings.get("playlist", {})

    trigger_change = bool(
        playlist.get("trigger_change", False)
    )

    mode = playlist.get("mode", "single")

    current_video = settings.get("selected_video", "")

    if not trigger_change:
        return current_video

    if mode not in ("random", "fixed"):
        return current_video

    order = playlist.get("order", [])

    active_files = []

    schedule_active = is_current_schedule_active()
    current_category = None

    if schedule_active:
        current_category = get_current_scheduler_category()

    for video in order:
        filename = video.get("filename", "")

        if not filename:
            continue

        if not video.get("active", True):
            continue

        video_path = VIDEO_FOLDER / filename

        if not video_path.exists():
            continue

        if current_category:
            if current_category not in video.get("tags", []):
                continue

        active_files.append(filename)

    if len(active_files) < 2:
        log("Trigger Change enabled but fewer than two active videos are available.", "PLAYBACK")
        return current_video

    current_filename = Path(current_video).name if current_video else ""

    if mode == "random":
        choices = [
            filename
            for filename in active_files
            if filename != current_filename
        ]

        if not choices:
            return current_video

        new_filename = random.choice(choices)

    else:
        if current_filename in active_files:
            current_index = active_files.index(current_filename)
            new_filename = active_files[
                (current_index + 1) % len(active_files)
            ]
        else:
            new_filename = active_files[0]

    new_path = str(VIDEO_FOLDER / new_filename)

    if new_path != current_video:
        settings["selected_video"] = new_filename

        try:
            with open(HOME / "settings.json", "w") as f:
                json.dump(settings, f, indent=2)

            log(f"Trigger Change selected '{new_filename}' using {mode} mode.", "PLAYBACK")

        except Exception as e:
            log(f"Failed to save Trigger Change selection: {e}", "ERROR")
            return current_video

    return new_path


def trigger_change_after_playback():
    global current_playback_path

    try:
        secondary_video_mode = get_secondary_video_mode()

        if secondary_video_mode != "playlist":
            return

        previous_path = get_selected_video()

        if not previous_path:
            return

        new_path = change_video_on_trigger()

        if new_path and new_path != previous_path:
            log(f"Trigger Change: {Path(previous_path).name} -> {Path(new_path).name}", "PLAYBACK")

            with playback_lock:
                load_and_pause(new_path)
                current_playback_path = str(Path(new_path))

            log(f"Trigger Change loaded '{Path(new_path).name}' and is waiting for trigger.", "PLAYBACK")
        else:
            log("Trigger Change did not change the selected video.", "PLAYBACK")

    except Exception as e:
        log(f"Secondary Trigger Change error: {type(e).__name__}: {e}", "ERROR")


def monitor_scheduled_playback(media_path):
    while True:
        try:
            with playback_lock:
                state = player.get_state()
                active_path = current_playback_path

            if state == vlc.State.Ended:
                if active_path == media_path:
                    trigger_change_after_playback()
                return

            if state == vlc.State.Stopped:
                return

            time.sleep(0.1)

        except Exception as e:
            log(f"Secondary scheduled playback monitor error: {type(e).__name__}: {e}", "ERROR")
            return


def start_scheduled_playback_monitor(media_path):
    monitor_thread = threading.Thread(
        target=monitor_scheduled_playback,
        args=(media_path,),
        daemon=True
    )
    monitor_thread.start()


def play_selected_video():
    global current_playback_path

    media_path = get_selected_video()

    if not media_path:
        log("No video selected to play.", "PLAYBACK")
        return

    media_path = Path(media_path)

    if not media_path.exists():
        log(f"Selected video does not exist: {media_path}", "PLAYBACK")
        return

    log(f"Playing selected video: {media_path.name}", "PLAYBACK")

    with playback_lock:
        media = instance.media_new(str(media_path))
        player.set_media(media)
        player.play()
        current_playback_path = str(media_path)

    sleep(0.5)

    while player.get_state() not in (
        vlc.State.Ended,
        vlc.State.Stopped
    ):
        sleep(0.1)

    naturally_ended = player.get_state() == vlc.State.Ended

    with playback_lock:
        player.pause()
        player.set_time(0)

    log("Video ended. Reset to beginning and paused.", "PLAYBACK")

    if naturally_ended:
        trigger_change_after_playback()


def switch_playlist_video(media_path):
    global current_playback_path

    media_path = Path(media_path)

    if not media_path.exists():
        log(f"Playlist video does not exist: {media_path}", "PLAYBACK")
        return

    with playback_lock:
        load_and_pause(str(media_path))
        current_playback_path = str(media_path)

    log(f"Secondary Playlist loaded '{media_path.name}' and is waiting for trigger.", "PLAYBACK")


def playlist_playback_worker():
    global current_playback_path

    while not stop_playlist_thread.is_set():
        try:
            secondary_video_mode = get_secondary_video_mode()

            if secondary_video_mode != "playlist":
                time.sleep(1)
                continue

            if read_pause_flag() or not is_schedule_enabled_now():
                time.sleep(1)
                continue

            selected_video = get_selected_video()

            if not selected_video:
                time.sleep(1)
                continue

            selected_path = Path(selected_video)

            if not selected_path.exists():
                time.sleep(1)
                continue

            selected_path_str = str(selected_path)

            if current_playback_path != selected_path_str:
                switch_playlist_video(selected_path_str)

            time.sleep(1)

        except Exception as e:
            log(f"Secondary Playlist playback error: {type(e).__name__}: {e}", "ERROR")
            time.sleep(1)


def load_pause_video():
    global current_playback_path

    log("Loading pause video.", "PLAYBACK")

    with playback_lock:
        player.stop()
        load_and_pause(str(PAUSE_VIDEO))
        current_playback_path = str(PAUSE_VIDEO)

    log(f"Loaded pause screen: {PAUSE_VIDEO.name}", "PLAYBACK")


def load_selected_video_paused():
    global current_playback_path

    media_path = get_selected_video()

    if not media_path:
        log("No selected video found.", "VIDEO")
        return

    with playback_lock:
        load_and_pause(media_path)
        current_playback_path = str(Path(media_path))

    log(f"Loaded selected video in paused state: {Path(media_path).name}", "PLAYBACK")


def prepare_sync_video(sync_tag, sync_id, sync_mode=None):
    global current_sync_tag
    global current_sync_id
    global current_sync_path

    if not sync_tag:
        log("Received empty Sync Tag.", "SYNC")
        return

    log(f"Preparing Sync Tag '{sync_tag}' (ID: {sync_id})", "SYNC")

    try:
        secondary_video_mode = get_secondary_video_mode()

        if sync_mode == "playlist":
            secondary_video_mode = "playlist"

        if secondary_video_mode == "playlist":
            matching_video = get_selected_video()

            if not matching_video:
                log("Secondary Playlist mode has no selected video available.", "SYNC")
                mqtt_client.publish(
                    mqtt_client.TOPIC_SYNC_STATUS,
                    {
                        "status": "unavailable",
                        "sync_tag": sync_tag,
                        "sync_id": sync_id
                    }
                )
                return

            matching_video = Path(matching_video)

            if not matching_video.exists():
                log(f"Secondary Playlist selected video does not exist: {matching_video}", "SYNC")
                mqtt_client.publish(
                    mqtt_client.TOPIC_SYNC_STATUS,
                    {
                        "status": "unavailable",
                        "sync_tag": sync_tag,
                        "sync_id": sync_id
                    }
                )
                return

            log(f"Secondary Playlist mode selected '{matching_video.name}'. Ignoring Primary Sync Tag '{sync_tag}'.", "SYNC")

        else:
            with open(HOME / "settings.json", "r") as f:
                settings = json.load(f)

            order = settings.get("playlist", {}).get("order", [])
            matching_video = None

            for video in order:
                video_sync_tag = video.get("sync_tag", "").strip()

                if video_sync_tag.lower() != sync_tag.lower():
                    continue

                if not video.get("active", True):
                    continue

                filename = video.get("filename", "").strip()

                if not filename:
                    continue

                video_path = VIDEO_FOLDER / filename

                if not video_path.exists():
                    log(f"Sync Tag '{sync_tag}' matched '{filename}', but file does not exist.", "SYNC")
                    continue

                matching_video = video_path
                break

            if matching_video is None:
                log(f"Sync Tag '{sync_tag}' not available on this Secondary.", "SYNC")
                mqtt_client.publish(
                    mqtt_client.TOPIC_SYNC_STATUS,
                    {
                        "status": "unavailable",
                        "sync_tag": sync_tag,
                        "sync_id": sync_id
                    }
                )
                return

            settings["selected_video"] = matching_video.name

            with open(HOME / "settings.json", "w") as f:
                json.dump(settings, f, indent=2)

            log(f"Updated selected_video for Preview: {matching_video.name}", "SYNC")

        with scheduled_play_lock:
            if scheduled_play_timer is not None:
                try:
                    scheduled_play_timer.cancel()
                except Exception:
                    pass

        prepare_media_for_sync(str(matching_video))

        current_sync_tag = sync_tag
        current_sync_id = sync_id
        current_sync_path = str(matching_video)

        log(f"Prepared '{matching_video.name}' for Sync ID {sync_id}", "SYNC")

        mqtt_client.publish(
            mqtt_client.TOPIC_SYNC_STATUS,
            {
                "status": "ready",
                "sync_tag": sync_tag,
                "sync_id": sync_id
            }
        )

        log(f"READY sent for Sync ID {sync_id}", "SYNC")

    except Exception as e:
        log(f"Failed to prepare Secondary video for Sync ID {sync_id}: {e}", "ERROR")

        mqtt_client.publish(
            mqtt_client.TOPIC_SYNC_STATUS,
            {
                "status": "unavailable",
                "sync_tag": sync_tag,
                "sync_id": sync_id
            }
        )


def scheduled_play(start_at_ms, sync_id):
    global current_sync_id
    global current_sync_path
    global current_playback_path

    if current_sync_id != sync_id:
        log(f"Ignoring play_at. Sync ID mismatch. Prepared: {current_sync_id}, Received: {sync_id}", "SYNC")
        return

    if not current_sync_path:
        log(f"Ignoring play_at. No prepared video for Sync ID {sync_id}.", "SYNC")
        return

    media_path = current_sync_path

    if not Path(media_path).exists():
        log(f"Ignoring play_at. Prepared video no longer exists: {media_path}", "SYNC")
        return

    log(f"Playing prepared Secondary video: {Path(media_path).name}", "SYNC")

    now_ms = time.time() * 1000
    delay_ms = start_at_ms - now_ms

    log(f"Target: {start_at_ms:.3f} ms", "SYNC")
    log(f"Current: {now_ms:.3f} ms", "SYNC")
    log(f"Waiting approximately {max(0, delay_ms):.3f} ms", "SYNC")

    if delay_ms > 10:
        time.sleep((delay_ms - 5) / 1000)

    while time.time() * 1000 < start_at_ms:
        time.sleep(0.0005)

    actual_ms = time.time() * 1000

    log(f"Secondary target reached. Actual: {actual_ms:.3f} ms Difference: {actual_ms - start_at_ms:+.3f} ms", "SYNC")

    with playback_lock:
        player.play()
        current_playback_path = media_path

    log(f"Secondary VLC PLAY command executed for Sync ID {sync_id}.", "SYNC")

    start_scheduled_playback_monitor(media_path)


def on_message(client, userdata, msg):
    global scheduled_play_timer

    try:
        message = json.loads(msg.payload.decode())
    except Exception:
        log(f"Invalid MQTT message: {msg.payload.decode()}", "ERROR")
        return

    command = message.get("command")

    log(f"MQTT command received: {command}", "MQTT")

    if command == "prepare_sync":
        sync_tag = message.get("sync_tag")
        sync_id = message.get("sync_id")
        sync_mode = message.get("sync_mode")

        if not sync_tag:
            log("prepare_sync received without sync_tag.", "SYNC")
            return

        if sync_id is None:
            log("prepare_sync received without sync_id.", "SYNC")
            return

        if sync_mode:
            log(f"prepare_sync received with Sync Mode: {sync_mode}", "SYNC")

        prepare_sync_video(
            sync_tag,
            sync_id,
            sync_mode
        )

    elif command == "play_at":
        start_at_ms = message.get("start_at_ms")
        sync_id = message.get("sync_id")

        if start_at_ms is None:
            log("play_at received without start_at_ms.", "SYNC")
            return

        if sync_id is None:
            log("play_at received without sync_id.", "SYNC")
            return

        try:
            start_at_ms = float(start_at_ms)
        except (TypeError, ValueError):
            log(f"Invalid start_at_ms: {start_at_ms}", "ERROR")
            return

        log(f"Received scheduled PLAY for {start_at_ms:.3f} ms (Sync ID: {sync_id})", "SYNC")

        with scheduled_play_lock:
            if scheduled_play_timer is not None:
                try:
                    scheduled_play_timer.cancel()
                except Exception:
                    pass

            delay_seconds = max(
                0,
                (start_at_ms - time.time() * 1000) / 1000
            )

            scheduled_play_timer = threading.Timer(
                delay_seconds,
                scheduled_play,
                args=(start_at_ms, sync_id)
            )

            scheduled_play_timer.daemon = True
            scheduled_play_timer.start()

    elif command == "play":
        write_pause_flag(False)
        play_selected_video()

    elif command == "resume":
        write_pause_flag(False)
        load_selected_video_paused()

    elif command == "pause":
        with scheduled_play_lock:
            if scheduled_play_timer is not None:
                try:
                    scheduled_play_timer.cancel()
                except Exception:
                    pass

        write_pause_flag(True)
        load_pause_video()

    else:
        log(f"Unknown MQTT command: {command}", "MQTT")


def on_exit():
    try:
        if player:
            player.stop()
    except Exception:
        pass

    log("Secondary script is exiting.", "SYSTEM")


atexit.register(on_exit)


def main():
    global player
    global instance
    global playlist_thread
    global playlist_playback_thread

    log("SECONDARY MODE STARTED", "SYSTEM")

    if not VIDEO_FOLDER.exists():
        log(f"Folder {VIDEO_FOLDER} not found.", "ERROR")
        sys.exit(1)

    video_files = sorted(VIDEO_FOLDER.glob("*.mp4"))

    if not video_files:
        log("No videos found!", "VIDEO")
        sys.exit(1)

    log(f"Found {len(video_files)} video(s)", "VIDEO")

    update_playlist_timestamp_on_startup()

    playlist_thread = threading.Thread(
        target=playlist_updater,
        daemon=True
    )

    playlist_thread.start()

    log("Started playlist updater thread.", "SYSTEM")

    instance = vlc.Instance()
    player = instance.media_player_new()

    pause_flag = read_pause_flag()
    schedule_enabled = is_schedule_enabled_now()

    if pause_flag or not schedule_enabled:
        load_pause_video()
    else:
        load_selected_video_paused()

    playlist_playback_thread = threading.Thread(
        target=playlist_playback_worker,
        daemon=True
    )

    playlist_playback_thread.start()

    log("Started Secondary Playlist playback thread.", "SYSTEM")

    mqtt_client.client.on_message = on_message

    log("Waiting for MQTT commands...", "MQTT")

    try:
        while True:
            sleep(1)

    except KeyboardInterrupt:
        log("Exiting.", "SYSTEM")

    finally:
        with scheduled_play_lock:
            if scheduled_play_timer is not None:
                try:
                    scheduled_play_timer.cancel()
                except Exception:
                    pass

        try:
            player.stop()
        except Exception:
            pass

        stop_playlist_thread.set()
        playlist_thread.join(timeout=2)
        playlist_playback_thread.join(timeout=2)


if __name__ == "__main__":
    main()