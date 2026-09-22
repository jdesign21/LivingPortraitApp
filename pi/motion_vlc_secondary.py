#!/usr/bin/env python3

import vlc
import sys
import atexit
import threading
import os
import json
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

# --------------------------------------------------
# VLC helpers
# --------------------------------------------------

def load_and_pause(media_path):
    media = instance.media_new(media_path)
    player.set_media(media)
    player.play()
    sleep(0.5)
    player.set_pause(1)
    player.set_time(0)


def play_selected_video():
    media_path = get_selected_video()

    if not media_path:
        log("No video selected to play.")
        return

    log(f"Playing selected video: {Path(media_path).name}")

    media = instance.media_new(media_path)
    player.set_media(media)
    player.play()
    sleep(0.5)

    # Wait for video to finish
    while player.get_state() not in (
        vlc.State.Ended,
        vlc.State.Stopped
    ):
        sleep(0.1)

    # Reset video to beginning and pause
    player.pause()
    player.set_time(0)

    log("Video ended. Reset to beginning and paused.")


def load_pause_video():
    log("Loading pause video.")

    if player.is_playing():
        player.stop()

    load_and_pause(str(PAUSE_VIDEO))

    log(f"[PAUSED] Loaded pause screen: {PAUSE_VIDEO.name}")


def load_selected_video_paused():
    media_path = get_selected_video()

    if not media_path:
        log("No selected video found.")
        return

    if player.is_playing():
        player.stop()

    load_and_pause(media_path)

    log(
        f"Loaded selected video in paused state: "
        f"{Path(media_path).name}"
    )


# --------------------------------------------------
# MQTT
# --------------------------------------------------

def on_message(client, userdata, msg):
    try:
        message = json.loads(msg.payload.decode())
    except Exception:
        log(f"Invalid MQTT message: {msg.payload.decode()}")
        return

    command = message.get("command")

    log(f"MQTT command received: {command}")

    if command == "play":
        play_selected_video()

    elif command == "pause":
        load_pause_video()

    else:
        log(f"Unknown MQTT command: {command}")


# --------------------------------------------------
# Exit
# --------------------------------------------------

def on_exit():
    try:
        if player:
            player.stop()
    except Exception:
        pass

    log("[EXIT] Secondary script is exiting.")


atexit.register(on_exit)


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    global player
    global instance

    log("SECONDARY MODE STARTED")

    if not VIDEO_FOLDER.exists():
        log(f"Folder {VIDEO_FOLDER} not found")
        sys.exit(1)

    video_files = sorted(VIDEO_FOLDER.glob("*.mp4"))

    if not video_files:
        log("No videos found!")
        sys.exit(1)

    log(f"Found {len(video_files)} video(s)")

    # Start playlist updater
    update_playlist_timestamp_on_startup()

    global playlist_thread
    playlist_thread = threading.Thread(
        target=playlist_updater,
        daemon=True
    )
    playlist_thread.start()

    log("Started playlist updater thread")

    # VLC setup
    instance = vlc.Instance()
    player = instance.media_player_new()

    # --------------------------------------------------
    # Determine initial state
    # --------------------------------------------------

    pause_flag = read_pause_flag()
    schedule_enabled = is_schedule_enabled_now()

    if pause_flag or not schedule_enabled:
        load_pause_video()
    else:
        load_selected_video_paused()

    # --------------------------------------------------
    # MQTT listener
    # --------------------------------------------------

    mqtt_client.client.on_message = on_message
    #mqtt_client.client.subscribe(mqtt_client.TOPIC_CONTROL)

    log("Waiting for MQTT commands...")

    try:
        while True:
            sleep(1)

    except KeyboardInterrupt:
        log("Exiting")

    finally:
        try:
            player.stop()
        except Exception:
            pass

        stop_playlist_thread.set()
        playlist_thread.join(timeout=2)


if __name__ == "__main__":
    main()

