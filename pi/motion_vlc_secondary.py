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
# MQTT synchronized playback
# --------------------------------------------------

def scheduled_play(start_at_ms):
    media_path = get_selected_video()

    if not media_path:
        log("No video selected to play.")
        return

    log(
        f"[SYNC] Preparing Secondary video: "
        f"{Path(media_path).name}"
    )

    media = instance.media_new(media_path)
    player.set_media(media)

    now_ms = time.time() * 1000
    delay_ms = start_at_ms - now_ms

    log(f"[SYNC] Target: {start_at_ms:.3f} ms")
    log(f"[SYNC] Current: {now_ms:.3f} ms")
    log(
        f"[SYNC] Waiting approximately "
        f"{max(0, delay_ms):.3f} ms"
    )

    # Wait until approximately 5 ms before target
    if delay_ms > 10:
        time.sleep((delay_ms - 5) / 1000)

    # Precise final wait
    while time.time() * 1000 < start_at_ms:
        time.sleep(0.0005)

    actual_ms = time.time() * 1000

    log(
        f"[SYNC] Secondary target reached. "
        f"Actual: {actual_ms:.3f} ms "
        f"Difference: {actual_ms - start_at_ms:+.3f} ms"
    )

    player.play()

    log("[SYNC] Secondary VLC PLAY command executed.")


def on_message(client, userdata, msg):
    global scheduled_play_timer

    try:
        message = json.loads(msg.payload.decode())
    except Exception:
        log(f"Invalid MQTT message: {msg.payload.decode()}")
        return

    command = message.get("command")

    log(f"MQTT command received: {command}")

    # --------------------------------------------------
    # Synchronized play
    # --------------------------------------------------

    if command == "play_at":

        start_at_ms = message.get("start_at_ms")

        if start_at_ms is None:
            log("[SYNC] play_at received without start_at_ms")
            return

        try:
            start_at_ms = float(start_at_ms)
        except (TypeError, ValueError):
            log(f"[SYNC] Invalid start_at_ms: {start_at_ms}")
            return

        log(
            f"[SYNC] Received scheduled PLAY for "
            f"{start_at_ms:.3f} ms"
        )

        with scheduled_play_lock:

            # Cancel any previously scheduled playback
            if scheduled_play_timer is not None:
                try:
                    scheduled_play_timer.cancel()
                except Exception:
                    pass

            # Start preparing the video about 200 ms
            # before the target time.
            delay_seconds = max(
                0,
                (start_at_ms - time.time() * 1000) / 1000 - 0.200
            )

            scheduled_play_timer = threading.Timer(
                delay_seconds,
                scheduled_play,
                args=(start_at_ms,)
            )

            scheduled_play_timer.daemon = True
            scheduled_play_timer.start()

    # --------------------------------------------------
    # Original immediate play command
    # --------------------------------------------------

    elif command == "play":
        play_selected_video()

    # --------------------------------------------------
    # Pause
    # --------------------------------------------------

    elif command == "pause":

        with scheduled_play_lock:

            if scheduled_play_timer is not None:
                try:
                    scheduled_play_timer.cancel()
                except Exception:
                    pass

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

    log("Waiting for MQTT commands...")

    try:
        while True:
            sleep(1)

    except KeyboardInterrupt:
        log("Exiting")

    finally:
        # Cancel any scheduled playback
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