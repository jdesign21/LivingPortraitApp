#!/usr/bin/env python3
import vlc
import sys
import atexit
import threading
import os
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
    is_schedule_enabled_now
)

from shared.vlc_network_helper import is_enabled

HOME = Path(os.path.expanduser("~"))

LOG_FOLDER = HOME / "logs"
VIDEO_FOLDER = HOME / "videos"
PAUSE_VIDEO = HOME / "pause_video" / "paused_rotated.mp4"

# Track the video currently being played
last_played_path = None

# Make sure the log folder exists
LOG_FOLDER.mkdir(parents=True, exist_ok=True)

# Global player object
player = None


def on_exit():
    try:
        player.stop()
    except Exception:
        pass
    log("[EXIT] Script is exiting.")


atexit.register(on_exit)


# Helper: load and pause a media file
def load_and_pause(media_path):
    media = vlc.Media(media_path)
    player.set_media(media)
    player.play()
    sleep(0.5)
    player.set_pause(1)
    player.set_time(0)


# Helper: play video endlessly until paused
def play_endless():
    global last_played_path

    log("Triggered mode OFF — playing video endlessly.")

    if not last_played_path:
        log("No video selected to play.")
        return

    while True:
        # Always play the video currently tracked by last_played_path.
        # If Fixed/Random changes selected_video while this video is
        # playing, the current video continues until it ends.
        media = vlc.Media(last_played_path)
        player.set_media(media)
        player.play()
        sleep(0.5)

        # Wait until video ends or pause is triggered
        while player.get_state() not in (
            vlc.State.Ended,
            vlc.State.Stopped
        ):
            if read_pause_flag() or not is_schedule_enabled_now():
                log("Pause detected mid-playback. Stopping video.")
                player.stop()
                return

            if get_triggered_flag():
                log(
                    "Triggered flag changed to ON during endless loop. "
                    "Switching mode."
                )
                player.stop()
                return

            sleep(0.1)

        log("Video ended. Checking for next video.")

        # After the current video finishes, check whether Fixed/Random
        # selected a different video.
        selected_path = get_selected_video()

        if selected_path and selected_path != last_played_path:
            log(
                f"Video change detected: "
                f"{Path(last_played_path).name} -> "
                f"{Path(selected_path).name}"
            )
            last_played_path = selected_path

        # Let VLC settle before the next playback cycle
        sleep(0.5)


# Helper: play video once with motion trigger and delay after
def play_triggered(delay_seconds):
    log("Waiting for motion...")
    pir.wait_for_motion()
    log("Motion detected! Playing video")

    if is_enabled():
        log(f"MQTT enabled: {mqtt_client.is_enabled()}")
        log(f"MQTT broker: {mqtt_client.BROKER}")

        result = mqtt_client.client.publish(
            mqtt_client.TOPIC_CONTROL,
            '{"command":"play"}'
        )

        log(f"MQTT publish result: {result.rc}")
        log("Sent PLAY command to Secondary Pis")

    media_path = get_selected_video()

    if media_path:
        media = vlc.Media(media_path)
        player.set_media(media)
        player.play()
        sleep(0.5)

        # Play until video ends or paused mid-playback
        while player.get_state() not in (
            vlc.State.Ended,
            vlc.State.Stopped
        ):
            if read_pause_flag() or not is_schedule_enabled_now():
                log("Pause detected mid-playback. Stopping video.")
                player.stop()
                break

            if not get_triggered_flag():
                log(
                    "Triggered flag turned OFF during playback. "
                    "Stopping video."
                )
                player.stop()
                break

            sleep(0.1)

        log(
            "Video ended or paused. "
            "Waiting delay before next motion..."
        )

        player.pause()
        player.set_time(0)

        # Delay before next motion detection
        if delay_seconds > 0:
            log(
                f"Waiting {delay_seconds} seconds before "
                f"listening for motion again."
            )
            sleep(delay_seconds)


def main():
    global player, pir, last_played_path

    log("SYSTEM HAS STARTED")

    if not VIDEO_FOLDER.exists():
        print(f"Folder {VIDEO_FOLDER} not found")
        sys.exit(1)

    video_files = sorted(VIDEO_FOLDER.glob("*.mp4"))

    if not video_files:
        print("No videos found!")
        sys.exit(1)

    log(f"Found {len(video_files)} video(s)")

    # Initialize PIR sensor
    pir = MotionSensor(4)

    # Start playlist updater thread
    update_playlist_timestamp_on_startup()

    global playlist_thread
    playlist_thread = threading.Thread(
        target=playlist_updater,
        daemon=True
    )
    playlist_thread.start()

    log("Started playlist updater thread")

    # Start with selected or fallback video
    media_path = get_selected_video()

    if not media_path:
        media_path = str(video_files[0])
        log(f"Falling back to {media_path}")

    # Track the video that VLC should initially play.
    # Fixed/Random changes will be picked up after the current
    # video finishes.
    last_played_path = media_path

    # VLC setup using proper instance
    instance = vlc.Instance()
    player = instance.media_player_new()
    pause_media = instance.media_new(str(PAUSE_VIDEO))

    # Preload pause video
    paused_mode = False

    load_and_pause(media_path)

    log(
        f"Loaded video {Path(media_path).name} "
        f"in paused state"
    )

    try:
        while True:
            pause_flag = read_pause_flag()
            triggered_flag = get_triggered_flag()
            delay_seconds = get_trigger_delay_seconds()
            schedule_enabled = is_schedule_enabled_now()

            # Handle pause ON
            if (pause_flag or not schedule_enabled) and not paused_mode:
                log("Pause flag detected ON. " "Switching to pause screen.")

                if is_enabled():
                    mqtt_client.publish(
                        mqtt_client.TOPIC_CONTROL,
                        {"command": "pause"}
                    )

                    log("Sent PAUSE command to Secondary Pis")

                if player.is_playing():
                    player.stop()

                player.set_media(pause_media)
                player.play()
                sleep(0.5)
                player.set_pause(1)
                player.set_time(0)

                log(
                    f"[PAUSED] Loaded pause screen: "
                    f"{PAUSE_VIDEO.name}"
                )

                paused_mode = True

            # Handle pause OFF
            elif (
                not pause_flag
                and schedule_enabled
                and paused_mode
            ):
                log("[UNPAUSED] Pause flag cleared, " "returning to playback mode")

                if is_enabled():
                    mqtt_client.publish(
                        mqtt_client.TOPIC_CONTROL,
                        {"command": "play"}
                    )

                    log("Sent PLAY command to Secondary Pis")

                if player.is_playing():
                    player.stop()

                # Get the video selected while the pause screen
                # was active.
                new_path = get_selected_video()

                if new_path:
                    media_path = new_path

                    log(f"Updated video selection to " f"{Path(media_path).name}")

                # Synchronize the tracked playback video with
                # the currently selected video.
                last_played_path = media_path

                load_and_pause(media_path)

                paused_mode = False

            # Playback if not paused
            if not paused_mode:
                if not triggered_flag:
                    play_endless()
                else:
                    play_triggered(delay_seconds)
            else:
                sleep(1)

    except KeyboardInterrupt:
        log("Exiting")

        player.stop()

        stop_playlist_thread.set()
        playlist_thread.join()

        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        log("[CRASH] Uncaught exception:")
        log(traceback.format_exc())

        raise

