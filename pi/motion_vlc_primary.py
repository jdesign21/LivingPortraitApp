#!/usr/bin/env python3

import vlc
import sys
import atexit
import threading
import os
import json
import time
import uuid
import mqtt_client

from time import sleep
from gpiozero import MotionSensor
from pathlib import Path

from shared.vlc_helper import (
    log,
    playlist_updater,
    stop_playlist_thread,
    update_playlist_timestamp_on_startup,
    get_selected_video,
    read_pause_flag,
    get_triggered_flag,
    get_trigger_delay_seconds,
    is_schedule_enabled_now,
    set_selection_sync_callback
)

from shared.vlc_network_helper import (
    is_enabled,
    get_sync_start_delay_ms
)


HOME = Path(os.path.expanduser("~"))
LOG_FOLDER = HOME / "logs"
VIDEO_FOLDER = HOME / "videos"
PAUSE_VIDEO = HOME / "pause_video" / "paused_rotated.mp4"

last_played_path = None

LOG_FOLDER.mkdir(parents=True, exist_ok=True)

player = None


# ============================================================
# Sync Status Tracking
# ============================================================

sync_status_lock = threading.Lock()
current_sync_id = None
current_sync_tag = None
sync_secondary_status = {}


def on_sync_status_message(client, userdata, msg):
    global current_sync_id
    global current_sync_tag

    try:
        message = json.loads(msg.payload.decode())
    except Exception:
        log(f"Invalid sync status message: {msg.payload.decode()}", "ERROR")
        return

    status = message.get("status")
    sync_tag = message.get("sync_tag")
    sync_id = message.get("sync_id")

    if not status:
        log("Sync status message missing status.", "ERROR")
        return

    if sync_id is None:
        log("Sync status message missing sync_id.", "ERROR")
        return

    with sync_status_lock:
        if sync_id != current_sync_id:
            log(f"Ignoring stale status message. Received ID: {sync_id}, Current ID: {current_sync_id}", "SYNC")
            return

        sender = getattr(msg, "mid", None)

        if sender is None:
            sender = "unknown"

        sync_secondary_status[str(sender)] = status

    log(f"Secondary status received: {status.upper()} Sync Tag '{sync_tag}' (ID: {sync_id})", "SYNC")

    if status == "ready":
        log(f"Secondary reported READY for Sync Tag '{sync_tag}' (ID: {sync_id})", "SYNC")

    elif status == "unavailable":
        log(f"Secondary reported UNAVAILABLE for Sync Tag '{sync_tag}' (ID: {sync_id})", "SYNC")

    else:
        log(f"Unknown Secondary sync status: {status}", "SYNC")


def register_sync_event(sync_tag, sync_id):
    global current_sync_id
    global current_sync_tag

    with sync_status_lock:
        current_sync_id = sync_id
        current_sync_tag = sync_tag
        sync_secondary_status.clear()

    log(f"Registered Sync ID {sync_id} for Sync Tag '{sync_tag}'", "SYNC")


def on_exit():
    try:
        player.stop()
    except Exception:
        pass

    log("Script is exiting.", "SYSTEM")


atexit.register(on_exit)


# ============================================================
# VLC Helpers
# ============================================================

def load_and_pause(media_path):
    media = vlc.Media(media_path)

    player.set_media(media)
    player.play()

    sleep(0.5)

    player.set_pause(1)
    player.set_time(0)


# ============================================================
# Sync Tag Helpers
# ============================================================

def get_video_sync_tag(media_path):
    if not media_path:
        return None

    filename = Path(media_path).name

    try:
        with open(HOME / "settings.json", "r") as f:
            settings = json.load(f)

        order = settings.get("playlist", {}).get("order", [])

        for video in order:
            if video.get("filename", "") != filename:
                continue

            sync_tag = video.get("sync_tag", "").strip()

            if sync_tag:
                return sync_tag

            return None

    except Exception as e:
        log(f"Failed to get Sync Tag for '{filename}': {e}", "ERROR")

    return None


def generate_sync_id():
    return uuid.uuid4().hex


def prepare_secondary_for_sync(sync_tag, sync_id):
    message = {
        "command": "prepare_sync",
        "sync_tag": sync_tag,
        "sync_id": sync_id
    }

    result = mqtt_client.client.publish(
        mqtt_client.TOPIC_CONTROL,
        json.dumps(message)
    )

    log(f"Sent PREPARE_SYNC for Sync Tag '{sync_tag}' (ID: {sync_id})", "SYNC")
    log(f"MQTT publish result: {result.rc}", "MQTT")


def sync_selected_video(video_name, sync_tag):
    if not sync_tag:
        log(f"Selected video '{Path(video_name).name}' has no Sync Tag. Secondary preparation skipped.", "SYNC")
        return

    if not is_enabled():
        return

    if not mqtt_client.client.is_connected():
        log("MQTT is enabled but not connected. Selection sync skipped.", "SYNC")
        return

    sync_id = generate_sync_id()

    register_sync_event(sync_tag, sync_id)

    log(f"Selection changed to '{Path(video_name).name}' with Sync Tag '{sync_tag}'. Sync ID: {sync_id}", "SYNC")

    prepare_secondary_for_sync(sync_tag, sync_id)


# ============================================================
# Endless Playback
# ============================================================

def play_endless():
    global last_played_path

    log("Triggered mode OFF — playing video endlessly.", "PLAYBACK")

    if not last_played_path:
        log("No video selected to play.", "VIDEO")
        return

    while True:
        media = vlc.Media(last_played_path)

        player.set_media(media)
        player.play()

        sleep(0.5)

        while player.get_state() not in (
            vlc.State.Ended,
            vlc.State.Stopped
        ):
            if read_pause_flag() or not is_schedule_enabled_now():
                log("Pause detected mid-playback. Stopping video.", "PLAYBACK")
                player.stop()
                return

            if get_triggered_flag():
                log("Triggered flag changed to ON during endless loop. Switching mode.", "PLAYBACK")
                player.stop()
                return

            selected_path = get_selected_video()

            if selected_path and selected_path != last_played_path:
                log(f"Video change detected: {Path(last_played_path).name} -> {Path(selected_path).name}", "PLAYBACK")

                last_played_path = selected_path

                sync_selected_video(
                    selected_path,
                    get_video_sync_tag(selected_path)
                )

                player.stop()
                break

            sleep(0.1)

        if player.get_state() in (
            vlc.State.Ended,
            vlc.State.Stopped
        ):
            selected_path = get_selected_video()

            if selected_path and selected_path != last_played_path:
                log(f"Video change detected: {Path(last_played_path).name} -> {Path(selected_path).name}", "PLAYBACK")

                last_played_path = selected_path

                sync_selected_video(
                    selected_path,
                    get_video_sync_tag(selected_path)
                )

        sleep(0.1)


# ============================================================
# Triggered Playback With Synchronized MQTT
# ============================================================

def play_triggered(delay_seconds):
    global last_played_path

    log("Waiting for motion...", "MOTION")

    if pir.is_active:
        pir.wait_for_no_motion()

    while True:
        selected_path = get_selected_video()

        if selected_path and selected_path != last_played_path:
            log(f"Video change detected while waiting: {Path(last_played_path).name} -> {Path(selected_path).name}", "PLAYBACK")

            last_played_path = selected_path

            load_and_pause(selected_path)

            log(f"Loaded video {Path(selected_path).name} in paused state", "PLAYBACK")

            sync_selected_video(
                selected_path,
                get_video_sync_tag(selected_path)
            )

        if read_pause_flag() or not is_schedule_enabled_now():
            log("Pause or schedule disabled while waiting for motion.", "PLAYBACK")
            return

        if not get_triggered_flag():
            log("Triggered flag turned OFF while waiting for motion.", "PLAYBACK")
            return

        if pir.is_active:
            break

        sleep(0.1)

    log("Motion detected!", "MOTION")

    media_path = get_selected_video()

    if not media_path:
        log("No video selected to play.", "VIDEO")
        return

    last_played_path = media_path

    sync_tag = get_video_sync_tag(media_path)

    sync_id = None

    if sync_tag:
        log(f"Video '{Path(media_path).name}' has Sync Tag '{sync_tag}'", "SYNC")
    else:
        log(f"Video '{Path(media_path).name}' has no Sync Tag.", "SYNC")

    sync_enabled = (
        is_enabled()
        and mqtt_client.client.is_connected()
        and sync_tag
    )

    start_at_ms = None

    if sync_enabled:
        sync_id = generate_sync_id()

        register_sync_event(sync_tag, sync_id)

        log(f"Created Sync ID {sync_id} for Sync Tag '{sync_tag}'", "SYNC")

        prepare_secondary_for_sync(
            sync_tag,
            sync_id
        )

        sync_start_delay_ms = get_sync_start_delay_ms()

        start_at_ms = int(time.time() * 1000) + sync_start_delay_ms

        message = {
            "command": "play_at",
            "start_at_ms": start_at_ms,
            "sync_id": sync_id
        }

        log(f"Scheduling playback for {start_at_ms} ms (delay: {sync_start_delay_ms} ms)", "SYNC")

        result = mqtt_client.client.publish(
            mqtt_client.TOPIC_CONTROL,
            json.dumps(message)
        )

        log(f"MQTT publish result: {result.rc}", "MQTT")
        log(f"Sent PLAY_AT command for {start_at_ms} ms (Sync ID: {sync_id})", "SYNC")

    elif is_enabled() and not mqtt_client.client.is_connected():
        log("MQTT is enabled but not connected. Playing Primary locally.", "SYNC")

    elif is_enabled() and not sync_tag:
        log("Video has no Sync Tag. Playing Primary locally without synchronized playback.", "SYNC")

    media = vlc.Media(media_path)
    player.set_media(media)

    if start_at_ms is not None:
        now_ms = time.time() * 1000
        delay_ms = start_at_ms - now_ms

        log(f"Primary waiting {max(0, delay_ms):.3f} ms", "SYNC")

        if delay_ms > 10:
            time.sleep((delay_ms - 5) / 1000)

        while time.time() * 1000 < start_at_ms:
            time.sleep(0.0005)

        actual_ms = time.time() * 1000

        log(f"Primary target reached. Actual: {actual_ms:.3f} ms Difference: {actual_ms - start_at_ms:+.3f} ms", "SYNC")

    player.play()

    if sync_id:
        log(f"Primary VLC PLAY command executed for Sync ID {sync_id}.", "PLAYBACK")
    else:
        log("Primary VLC PLAY command executed.", "PLAYBACK")

    sleep(0.5)

    while player.get_state() not in (
        vlc.State.Ended,
        vlc.State.Stopped
    ):
        if read_pause_flag() or not is_schedule_enabled_now():
            log("Pause detected mid-playback. Stopping video.", "PLAYBACK")
            player.stop()
            break

        if not get_triggered_flag():
            log("Triggered flag turned OFF during playback. Stopping video.", "PLAYBACK")
            player.stop()
            break

        sleep(0.1)

    log("Video ended or paused. Waiting delay before next motion...", "PLAYBACK")

    player.pause()
    player.set_time(0)

    if delay_seconds > 0:
        log(f"Waiting {delay_seconds} seconds before listening for motion again.", "MOTION")
        sleep(delay_seconds)


# ============================================================
# Main
# ============================================================

def main():
    global player
    global pir
    global last_played_path

    log("SYSTEM HAS STARTED", "SYSTEM")

    if not VIDEO_FOLDER.exists():
        log(f"Folder {VIDEO_FOLDER} not found", "ERROR")
        sys.exit(1)

    video_files = sorted(VIDEO_FOLDER.glob("*.mp4"))
    no_videos_logged = False

    while not video_files:
        if not no_videos_logged:
            log("No videos found. Waiting for a video to be uploaded...", "VIDEO")
            no_videos_logged = True

        time.sleep(5)

        video_files = sorted(VIDEO_FOLDER.glob("*.mp4"))

    log(f"Found {len(video_files)} video(s)", "VIDEO")

    pir = MotionSensor(4)

    update_playlist_timestamp_on_startup()
    set_selection_sync_callback(sync_selected_video)

    global playlist_thread

    playlist_thread = threading.Thread(
        target=playlist_updater,
        daemon=True
    )

    playlist_thread.start()

    log("Started playlist updater thread", "SYSTEM")

    media_path = get_selected_video()

    if not media_path:
        media_path = str(video_files[0])
        log(f"Falling back to {media_path}", "VIDEO")

    last_played_path = media_path

    instance = vlc.Instance()
    player = instance.media_player_new()

    pause_media = instance.media_new(str(PAUSE_VIDEO))
    paused_mode = False

    load_and_pause(media_path)

    log(f"Loaded video {Path(media_path).name} in paused state", "PLAYBACK")


    #mqtt_client.client.on_message = on_sync_status_message
    #log("MQTT sync status listener registered.", "MQTT")

    mqtt_client.set_sync_status_handler(on_sync_status_message)
    log("MQTT sync status listener registered.", "MQTT")

    try:
        while True:
            pause_flag = read_pause_flag()
            triggered_flag = get_triggered_flag()
            delay_seconds = get_trigger_delay_seconds()
            schedule_enabled = is_schedule_enabled_now()

            if (pause_flag or not schedule_enabled) and not paused_mode:
                log("Pause flag detected ON. Switching to pause screen.", "PLAYBACK")

                if is_enabled():
                    mqtt_client.publish(
                        mqtt_client.TOPIC_CONTROL,
                        {"command": "pause"}
                    )

                    log("Sent PAUSE command to Secondary Pis", "MQTT")

                if player.is_playing():
                    player.stop()

                player.set_media(pause_media)
                player.play()

                sleep(0.5)

                player.set_pause(1)
                player.set_time(0)

                log(f"Loaded pause screen: {PAUSE_VIDEO.name}", "PLAYBACK")

                paused_mode = True

            elif (
                not pause_flag
                and schedule_enabled
                and paused_mode
            ):
                log("Pause flag cleared, returning to playback mode", "PLAYBACK")

                if is_enabled():
                    mqtt_client.publish(
                        mqtt_client.TOPIC_CONTROL,
                        {"command": "play"}
                    )

                    log("Sent PLAY command to Secondary Pis", "MQTT")

                if player.is_playing():
                    player.stop()

                new_path = get_selected_video()

                if new_path:
                    media_path = new_path
                    log(f"Updated video selection to {Path(media_path).name}", "VIDEO")

                last_played_path = media_path

                load_and_pause(media_path)

                paused_mode = False

            if not paused_mode:
                if not triggered_flag:
                    play_endless()
                else:
                    play_triggered(delay_seconds)
            else:
                sleep(1)

    except KeyboardInterrupt:
        log("Exiting", "SYSTEM")

        player.stop()

        stop_playlist_thread.set()
        playlist_thread.join()

        sys.exit(0)


if __name__ == "__main__":
    try:
        main()

    except Exception:
        import traceback

        log("Uncaught exception:", "ERROR")
        log(traceback.format_exc(), "ERROR")

        raise