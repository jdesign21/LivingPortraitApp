#!/usr/bin/env python3
import vlc
import sys
import atexit
import threading
import os
import json
import time
import mqtt_client
from time import sleep
from pathlib import Path
from shared.vlc_helper import (
    log,
    playlist_updater,
    stop_playlist_thread,
    update_playlist_timestamp_on_startup,
    get_selected_video,
    read_pause_flag,
    is_schedule_enabled_now
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
current_sync_tag = None
current_sync_id = None
current_sync_path = None

def load_and_pause(media_path):
    media = instance.media_new(media_path)
    player.set_media(media)
    player.play()
    sleep(0.5)
    player.set_pause(1)
    player.set_time(0)

def prepare_media_for_sync(media_path):
    """
    Load the Sync Tag video into VLC and leave it paused.
    This makes the new selection immediately visible and
    leaves the video ready for PLAY_AT.
    """
    if player.is_playing():
        player.stop()
    load_and_pause(media_path)

def play_selected_video():
    media_path = get_selected_video()
    if not media_path:
        log("No video selected to play.", "PLAYBACK")
        return
    log(f"Playing selected video: {Path(media_path).name}", "PLAYBACK")
    media = instance.media_new(media_path)
    player.set_media(media)
    player.play()
    sleep(0.5)
    while player.get_state() not in (
        vlc.State.Ended,
        vlc.State.Stopped
    ):
        sleep(0.1)
    player.pause()
    player.set_time(0)
    log("Video ended. Reset to beginning and paused.", "PLAYBACK")

def load_pause_video():
    log("Loading pause video.", "PLAYBACK")
    if player.is_playing():
        player.stop()
    load_and_pause(str(PAUSE_VIDEO))
    log(f"Loaded pause screen: {PAUSE_VIDEO.name}", "PLAYBACK")

def load_selected_video_paused():
    media_path = get_selected_video()
    if not media_path:
        log("No selected video found.", "VIDEO")
        return
    if player.is_playing():
        player.stop()
    load_and_pause(media_path)
    log(f"Loaded selected video in paused state: {Path(media_path).name}", "PLAYBACK")

def prepare_sync_video(sync_tag, sync_id):
    global current_sync_tag
    global current_sync_id
    global current_sync_path

    if not sync_tag:
        log("Received empty Sync Tag.", "SYNC")
        return

    log(f"Preparing Sync Tag '{sync_tag}' (ID: {sync_id})", "SYNC")

    try:
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

        log(f"Prepared '{matching_video.name}' for Sync Tag '{sync_tag}' (ID: {sync_id})", "SYNC")

        mqtt_client.publish(
            mqtt_client.TOPIC_SYNC_STATUS,
            {
                "status": "ready",
                "sync_tag": sync_tag,
                "sync_id": sync_id
            }
        )

        log(f"READY sent for Sync Tag '{sync_tag}' (ID: {sync_id})", "SYNC")

    except Exception as e:
        log(f"Failed to prepare Sync Tag '{sync_tag}': {e}", "ERROR")

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

    player.play()

    log(f"Secondary VLC PLAY command executed for Sync ID {sync_id}.", "SYNC")

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

        if not sync_tag:
            log("prepare_sync received without sync_tag.", "SYNC")
            return

        if sync_id is None:
            log("prepare_sync received without sync_id.", "SYNC")
            return

        prepare_sync_video(sync_tag, sync_id)

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
        play_selected_video()

    elif command == "pause":
        with scheduled_play_lock:
            if scheduled_play_timer is not None:
                try:
                    scheduled_play_timer.cancel()
                except Exception:
                    pass

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

    global playlist_thread

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

if __name__ == "__main__":
    main()