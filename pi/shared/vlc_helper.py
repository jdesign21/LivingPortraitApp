import json
import random
import threading
import time
import os
from datetime import datetime, timedelta
from pathlib import Path

# Paths
HOME = Path(os.path.expanduser("~"))
SETTINGS_FILE = HOME / "settings.json"
VIDEO_FOLDER = HOME / "videos"
LOG_FOLDER = HOME / "logs"
LOG_FOLDER.mkdir(exist_ok=True)

# Log retention
LOG_RETENTION_DAYS = 30


# Thread control
stop_playlist_thread = threading.Event()

# Primary Sync Tag callback
selection_sync_callback = None


def cleanup_old_logs():
    """Delete log files older than the configured retention period."""
    try:
        cutoff_time = time.time() - (
            LOG_RETENTION_DAYS * 24 * 60 * 60
        )

        removed_count = 0

        for log_file in LOG_FOLDER.glob("*.txt"):
            try:
                if log_file.stat().st_mtime < cutoff_time:
                    log_file.unlink()
                    removed_count += 1
            except Exception as e:
                log(
                    f"Failed to remove old log "
                    f"'{log_file.name}': {e}",
                    "ERROR"
                )

        if removed_count:
            log(
                f"Removed {removed_count} log file(s) "
                f"older than {LOG_RETENTION_DAYS} days.",
                "SYSTEM"
            )

    except Exception as e:
        log(
            f"Failed to clean up old logs: {e}",
            "ERROR"
        )


def get_version():
    version_file = HOME / "version.txt"

    try:
        with open(version_file, "r") as f:
            version = f.read().strip()

            if version:
                return version

            return "unknown"

    except FileNotFoundError:
        return "unknown"

    except Exception as e:
        log(
            f"Failed to read version.txt: {e}",
            "ERROR"
        )
        return "unknown"


def log(msg, category="SYSTEM"):
    """
    Write a standardized application log entry.

    The category is a free-form string used to classify
    the log entry for filtering and display.
    """
    timestamp = datetime.now().isoformat(
        timespec="seconds"
    )

    log_line = (
        f"[{timestamp}] [{category}] {msg}"
    )

    print(log_line)

    date_str = datetime.now().strftime(
        "%Y-%m-%d"
    )

    log_file = LOG_FOLDER / f"{date_str}.txt"

    with log_file.open("a") as f:
        f.write(f"{log_line}\n")


def load_settings():
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)

        settings_changed = False

        if "setup_complete" not in settings:
            existing_videos = list(VIDEO_FOLDER.glob("*.mp4"))
            settings["setup_complete"] = len(existing_videos) > 0
            settings_changed = True

    else:
        settings = {
            "setup_complete": False,
            "selected_video": "",
            "pause_flag": True,
            "mute_audio": False,
            "time_format": "12",
            "sync_tags": [],
            "schedule_tags": [
                {"id": "kid", "name": "Kid-Friendly"},
                {"id": "scary", "name": "Scary"}
            ],
            "playlist": {
                "mode": "single",
                "interval": 0,
                "last_updated": "",
                "order": [],
                "triggered_flag": True,
                "trigger_change": False,
                "delay": 0,
                "secondary_start_mode": "with_primary",
                "secondary_start_delay": 0,
                "secondary_video_mode": "sync_tag"
            }
        }

        settings_changed = True

    if "time_format" not in settings:
        settings["time_format"] = "12"
        settings_changed = True

    if settings.get("time_format") not in ("12", "24"):
        settings["time_format"] = "12"
        settings_changed = True

    if "sync_tags" not in settings:
        settings["sync_tags"] = []
        settings_changed = True

    if "mute_audio" not in settings:
        settings["mute_audio"] = False
        settings_changed = True

    if "schedule_tags" not in settings:
        settings["schedule_tags"] = [
            {"id": "kid", "name": "Kid-Friendly"},
            {"id": "scary", "name": "Scary"}
        ]
        settings_changed = True

    playlist = settings.setdefault("playlist", {})

    if "trigger_change" not in playlist:
        playlist["trigger_change"] = False
        settings_changed = True

    if "secondary_start_mode" not in playlist:
        playlist["secondary_start_mode"] = "with_primary"
        settings_changed = True

    if "secondary_start_delay" not in playlist:
        playlist["secondary_start_delay"] = 0
        settings_changed = True

    if "secondary_video_mode" not in playlist:
        playlist["secondary_video_mode"] = "sync_tag"
        settings_changed = True

    settings = migrate_days_slots(settings)

    if settings_changed:
        save_settings(settings)

    return settings


def save_settings(settings):
    temp_file = SETTINGS_FILE.with_suffix(".tmp")
    with open(temp_file, "w") as f:
        json.dump(settings, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_file, SETTINGS_FILE)


def get_mute_audio():
    settings = load_settings()
    return bool(settings.get("mute_audio", False))


def get_video_mute_audio(video_name):
    """
    Return the per-video mute setting.

    Videos that do not have the new mute_audio field
    default to False so their audio remains enabled.
    """
    if not video_name:
        return False

    filename = Path(video_name).name

    try:
        settings = load_settings()
        order = settings.get("playlist", {}).get("order", [])

        for video in order:
            if video.get("filename", "") != filename:
                continue

            return bool(video.get("mute_audio", False))

    except Exception as e:
        log(
            f"Failed to get per-video audio setting for "
            f"'{filename}': {e}",
            "ERROR"
        )

    return False


def get_playback_schedules(settings=None):
    """Return normalized independent playback schedule entries.

    Existing two-slots-per-day schedules are migrated once into this format.
    """
    if not isinstance(settings, dict):
        settings = load_settings()
    schedules = settings.get("playback_schedules")
    if isinstance(schedules, list):
        normalized = []
        for index, item in enumerate(schedules):
            if not isinstance(item, dict):
                continue
            days = item.get("days", [])
            if isinstance(days, str):
                days = [days]
            days = [day for day in days if day in (
                "Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"
            )]
            normalized.append({
                "id": str(item.get("id") or f"schedule-{index + 1}"),
                "name": str(item.get("name") or f"Schedule {index + 1}"),
                "enabled": bool(item.get("enabled", True)),
                "days": days,
                "start": str(item.get("start") or "00:00"),
                "end": str(item.get("end") or "23:59"),
                "category": str(item.get("category") or "")
            })
        return normalized

    legacy_days = settings.get("days", {})
    migrated = []
    day_names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    for day in day_names:
        day_data = legacy_days.get(day, {})
        for slot_name, slot in (("slot1", day_data.get("slot1", {})), ("slot2", day_data.get("slot2", {}))):
            if not slot.get("enabled", False):
                continue
            migrated.append({
                "id": f"{day.lower()}-{slot_name}",
                "name": f"{day} — {slot_name.replace('slot', 'Slot ')}",
                "enabled": True,
                "days": [day],
                "start": slot.get("start") or "00:00",
                "end": slot.get("end") or "23:59",
                "category": slot.get("category") or ""
            })
    if migrated:
        settings["playback_schedules"] = migrated
        save_settings(settings)
    else:
        settings["playback_schedules"] = []
        save_settings(settings)
    return migrated


def _schedule_time_matches(schedule, day_name, now):
    if not schedule.get("enabled", True):
        return False
    selected_days = schedule.get("days", [])
    if day_name not in selected_days:
        # For an overnight period, the after-midnight portion belongs to
        # the previous day's selected schedule.
        previous_day = (now - timedelta(days=1)).strftime("%A")
        if previous_day not in selected_days:
            return False
        try:
            overnight_end = datetime.strptime(schedule.get("end", "23:59"), "%H:%M").time()
            overnight_start = datetime.strptime(schedule.get("start", "00:00"), "%H:%M").time()
        except (TypeError, ValueError):
            return False
        return overnight_end <= overnight_start and now.time() < overnight_end
    try:
        start = datetime.strptime(schedule.get("start", "00:00"), "%H:%M").time()
        end = datetime.strptime(schedule.get("end", "23:59"), "%H:%M").time()
    except (TypeError, ValueError):
        return False
    current = now.time()
    if end > start:
        return start <= current < end
    # On the selected start day, the overnight period begins at start.
    return current >= start


def get_days_schedule():
    settings = load_settings()
    return settings.get("days", {})


def update_days_schedule(days_schedule):
    settings = load_settings()
    settings["days"] = days_schedule
    save_settings(settings)


def get_time_format(settings=None):
    """
    Return the configured display time format.

    An existing settings dictionary may be supplied to avoid reloading the
    settings file when several values are needed during one page request.

    Returns:
        "12" for 12-hour display.
        "24" for 24-hour display.
    """
    if not isinstance(settings, dict):
        settings = load_settings()
    time_format = settings.get("time_format", "12")

    if time_format not in ("12", "24"):
        return "12"

    return time_format


def migrate_days_slots(settings):
    """
    Ensure that 'days' in settings has slot1 and slot2 for each day.
    Migrates old start/end/category into slot1 if present.
    """
    days = settings.get("days", {})

    for day_name in [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday"
    ]:
        if day_name not in days:
            days[day_name] = {"enabled": True}

        day = days[day_name]

        if "slot1" not in day:
            day["slot1"] = {
                "enabled": day.get("enabled", False),
                "start": day.get("start", "00:00"),
                "end": day.get("end", "23:59"),
                "category": day.get("category", "")
            }

        if "slot2" not in day:
            day["slot2"] = {
                "enabled": False,
                "start": "",
                "end": "",
                "category": ""
            }

        day.pop("start", None)
        day.pop("end", None)
        day.pop("category", None)

    settings["days"] = days
    return settings


def get_triggered_flag():
    settings = load_settings()
    playlist = settings.get("playlist", {})
    flag = playlist.get("triggered_flag", False)
    return bool(flag)


def get_trigger_change():
    settings = load_settings()
    playlist = settings.get("playlist", {})
    return bool(playlist.get("trigger_change", False))


def get_trigger_delay_seconds():
    settings = load_settings()
    playlist = settings.get("playlist", {})
    delay = playlist.get("delay", 0)

    try:
        return int(delay)
    except (ValueError, TypeError):
        return 0


def get_secondary_start_mode():
    settings = load_settings()
    playlist = settings.get("playlist", {})
    return playlist.get("secondary_start_mode", "with_primary")


def get_secondary_start_delay_seconds():
    settings = load_settings()
    playlist = settings.get("playlist", {})
    delay = playlist.get("secondary_start_delay", 0)

    try:
        return int(delay)
    except (ValueError, TypeError):
        return 0


def get_secondary_video_mode():
    settings = load_settings()
    playlist = settings.get("playlist", {})
    return playlist.get("secondary_video_mode", "sync_tag")


def is_schedule_enabled_now(settings=None, now=None):
    """Return whether playback is permitted by the schedule at the supplied time."""
    if not isinstance(settings, dict):
        settings = load_settings()
    now = now if isinstance(now, datetime) else datetime.now()
    schedules = get_playback_schedules(settings)
    today = now.strftime("%A")
    today_schedules = [s for s in schedules if today in s.get("days", []) and s.get("enabled", True)]
    overnight_active = any(_schedule_time_matches(s, today, now) for s in schedules)
    if not today_schedules and not overnight_active:
        return True
    return overnight_active


def is_current_schedule_active():
    """True only when an enabled scheduled period is active (not the all-day fallback)."""
    settings = load_settings()
    now = datetime.now()
    today = now.strftime("%A")
    schedules = get_playback_schedules(settings)
    return any(_schedule_time_matches(s, today, now) for s in schedules)


def get_next_start_time(settings, time_format=None, now=None):
    """Return the next enabled schedule start time and its tag."""
    now = now if isinstance(now, datetime) else datetime.now()
    upcoming = []
    for schedule in get_playback_schedules(settings):
        if not schedule.get("enabled", True):
            continue
        for day in schedule.get("days", []):
            for offset in range(8):
                check_date = now.date() + timedelta(days=offset)
                if check_date.strftime("%A") != day:
                    continue
                try:
                    start_time = datetime.strptime(schedule.get("start", "00:00"), "%H:%M").time()
                except (TypeError, ValueError):
                    continue
                start_dt = datetime.combine(check_date, start_time)
                if start_dt > now:
                    upcoming.append((start_dt, schedule.get("category", "")))
    if not upcoming:
        return None, None
    next_start, category = min(upcoming, key=lambda item: item[0])
    time_format = time_format if time_format in ("12", "24") else get_time_format(settings)
    formatted = next_start.strftime("%H:%M" if time_format == "24" else "%I:%M %p")
    return f"{next_start.strftime('%A')} {formatted}", category


def get_current_scheduler_category():
    """Return the tag for the active schedule; overlapping schedules combine tags."""
    settings = load_settings()
    now = datetime.now()
    today = now.strftime("%A")
    active = [
        schedule for schedule in get_playback_schedules(settings)
        if _schedule_time_matches(schedule, today, now)
    ]
    # Existing playback code accepts one tag. The first active row wins;
    # an empty tag means all active videos are eligible for that period.
    return (active[0].get("category") or None) if active else None


def get_playlist_settings(settings=None):
    """Return playlist settings, optionally reusing an already-loaded settings dictionary."""
    if not isinstance(settings, dict):
        settings = load_settings()
    playlist = settings.get("playlist", {})

    return (
        playlist.get("mode", "single"),
        playlist.get("interval", 0),
        playlist.get("last_updated", ""),
        playlist.get("order", []),
        playlist.get("triggered_flag", False),
        playlist.get("delay", 0)
    )


def update_playlist_settings(
    mode=None,
    interval=None,
    last_updated=None,
    order=None,
    triggered_flag=None,
    trigger_change=None,
    delay=None,
    secondary_start_mode=None,
    secondary_start_delay=None,
    secondary_video_mode=None
):
    settings = load_settings()
    playlist = settings.get("playlist", {})

    if mode is not None:
        playlist["mode"] = mode
    if interval is not None:
        playlist["interval"] = interval
    if last_updated is not None:
        playlist["last_updated"] = last_updated
    if order is not None:
        playlist["order"] = order
    if triggered_flag is not None:
        playlist["triggered_flag"] = triggered_flag
    if trigger_change is not None:
        playlist["trigger_change"] = trigger_change
    if delay is not None:
        playlist["delay"] = delay
    if secondary_start_mode is not None:
        playlist["secondary_start_mode"] = secondary_start_mode
    if secondary_start_delay is not None:
        playlist["secondary_start_delay"] = secondary_start_delay
    if secondary_video_mode is not None:
        playlist["secondary_video_mode"] = secondary_video_mode

    settings["playlist"] = playlist
    save_settings(settings)


def update_playlist_timestamp_on_startup():
    try:
        settings = load_settings()
        playlist = settings.get("playlist", {})
        mode = playlist.get("mode", "single").lower()
        interval = playlist.get("interval", 0)
        last_updated_str = playlist.get("last_updated", "")

        if mode not in ("random", "fixed"):
            log(
                f"Playlist mode '{mode}' does not require "
                f"timestamp update.",
                "SYSTEM"
            )
            return

        now = datetime.now()
        last_updated = None

        if last_updated_str:
            try:
                last_updated = datetime.strptime(
                    last_updated_str,
                    "%Y-%m-%d %H:%M:%S"
                )
            except Exception as e:
                log(
                    f"Failed to parse last_updated timestamp: {e}",
                    "ERROR"
                )

        if interval > 0 and (
            not last_updated
            or (now - last_updated) >= timedelta(minutes=interval)
        ):
            new_timestamp = now.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            playlist["last_updated"] = new_timestamp
            settings["playlist"] = playlist
            save_settings(settings)

            log(
                f"Playlist mode '{mode}' detected. "
                f"Updated last_updated to: {new_timestamp}",
                "PLAYBACK"
            )
        else:
            log(
                "Playlist timestamp still valid or interval is zero, "
                "no update needed.",
                "SYSTEM"
            )

    except Exception as e:
        log(
            f"Failed to update playlist timestamp: {e}",
            "ERROR"
        )


def get_selected_video():
    try:
        settings = load_settings()
        selected_name = settings.get(
            "selected_video",
            ""
        ).strip()

        video_path = VIDEO_FOLDER / selected_name

        if selected_name and video_path.is_file():
            return str(video_path)

        if selected_name:
            log(
                f"Selected video {selected_name} not found; looking for an active replacement.",
                "VIDEO"
            )

        playlist = settings.get("playlist", {})
        order = playlist.get("order", [])

        # In Sync Tag mode, a Secondary must wait for the Primary to choose
        # the matching tagged video instead of selecting an unrelated file.
        try:
            network_settings = json.loads(
                (HOME / "network_pis.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            network_settings = {}

        if (
            network_settings.get("role") == "secondary"
            and playlist.get("secondary_video_mode", "sync_tag") == "sync_tag"
        ):
            if selected_name:
                settings["selected_video"] = ""
                save_settings(settings)
                log(
                    "Secondary is waiting for a valid Primary Sync Tag selection.",
                    "VIDEO"
                )
            return None

        schedule_active = is_current_schedule_active()
        current_category = (
            get_current_scheduler_category()
            if schedule_active
            else None
        )

        replacement = None
        for item in order:
            filename = item.get("filename", "").strip()
            if not filename or not item.get("active", True):
                continue
            if current_category and current_category not in item.get("tags", []):
                continue
            candidate = VIDEO_FOLDER / filename
            if candidate.is_file():
                replacement = filename
                break

        if replacement is None:
            log("No active existing video is available as a replacement.", "VIDEO")
            return None

        settings["selected_video"] = replacement
        save_settings(settings)
        log(f"Selected video updated to replacement: {replacement}", "VIDEO")
        return str(VIDEO_FOLDER / replacement)

    except Exception as e:
        log(
            f"Failed to read selected_video from settings.json: {e}",
            "ERROR"
        )
        return None


def get_sync_tag_for_video(video_name):
    """
    Return the Sync Tag assigned to a playlist video.
    Returns None when the video has no Sync Tag.
    """
    if not video_name:
        return None

    filename = Path(video_name).name

    try:
        settings = load_settings()
        order = settings.get(
            "playlist",
            {}
        ).get(
            "order",
            []
        )

        for video in order:
            if video.get("filename", "") != filename:
                continue

            sync_tag = video.get("sync_tag", "")

            if isinstance(sync_tag, str):
                sync_tag = sync_tag.strip()

            return sync_tag or None

    except Exception as e:
        log(
            f"Failed to get Sync Tag for '{filename}': {e}",
            "ERROR"
        )

    return None


def set_selection_sync_callback(callback):
    """
    Register a callback that is called whenever the Primary
    playlist selection changes.

    The callback receives:
        video_name
        sync_tag
    """
    global selection_sync_callback
    selection_sync_callback = callback


def notify_selection_sync(video_name):
    """
    Notify the Primary synchronization handler that the selected
    video changed.

    The Secondary will use the Sync Tag to select its own
    matching local video.
    """
    if selection_sync_callback is None:
        return

    sync_tag = get_sync_tag_for_video(video_name)

    try:
        selection_sync_callback(
            video_name,
            sync_tag
        )
    except Exception as e:
        log(
            f"Selection Sync callback failed for "
            f"'{video_name}': {e}",
            "SYNC"
        )


def change_video_for_trigger(mode, current_video):
    settings = load_settings()
    playlist = settings.get("playlist", {})
    order = playlist.get("order", [])

    current_category = get_current_scheduler_category()
    day_active = is_current_schedule_active()

    if day_active:
        active_files = [
            item["filename"]
            for item in order
            if item.get("active", True)
            and (
                not current_category
                or current_category in item.get("tags", [])
            )
        ]
    else:
        active_files = [
            item["filename"]
            for item in order
            if item.get("active", True)
        ]

    if len(active_files) < 2:
        return current_video

    current_filename = Path(current_video).name

    if mode == "random":
        other_choices = [
            filename
            for filename in active_files
            if filename != current_filename
        ]

        if not other_choices:
            return current_video

        new_video = random.choice(other_choices)

    elif mode == "fixed":
        if current_filename in active_files:
            current_index = active_files.index(
                current_filename
            )

            new_video = active_files[
                (current_index + 1) % len(active_files)
            ]
        else:
            new_video = active_files[0]

    else:
        return current_video

    new_path = VIDEO_FOLDER / new_video

    if not new_path.exists():
        log(
            f"Trigger Change selected missing video: {new_video}",
            "ERROR"
        )
        return current_video

    if new_video == current_filename:
        return current_video

    settings["selected_video"] = new_video
    settings["playlist"]["last_updated"] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    save_settings(settings)

    log(
        f"Trigger Change: {current_filename} -> {new_video}",
        "PLAYBACK"
    )

    notify_selection_sync(new_video)

    return str(new_path)


def read_pause_flag():
    try:
        settings = load_settings()
        return settings.get("pause_flag", False)
    except Exception as e:
        log(
            f"Failed to read pause_flag from settings.json: {e}",
            "ERROR"
        )
        return False


def write_pause_flag(is_paused):
    settings = load_settings()
    settings["pause_flag"] = is_paused
    save_settings(settings)


def playlist_updater():
    while not stop_playlist_thread.is_set():
        try:
            settings = load_settings()
            playlist = settings.get("playlist", {})
            secondary_video_mode = playlist.get(
                "secondary_video_mode",
                "sync_tag"
            )
            trigger_change = bool(
                playlist.get(
                    "trigger_change",
                    False
                )
            )

            (
                mode,
                interval,
                last_updated,
                order,
                triggered_flag,
                delay
            ) = get_playlist_settings()

            pause_flag = read_pause_flag()
            day_active = is_current_schedule_active()
            current_category = (
                get_current_scheduler_category()
                if day_active
                else None
            )

            # A Secondary using Match Sync Tag must not independently
            # change its selected video. The Primary controls selection.
            if (
                secondary_video_mode == "sync_tag"
                and selection_sync_callback is None
            ):
                time.sleep(1)
                continue

            # Do not change the selected video while paused.
            if pause_flag:
                time.sleep(1)
                continue

            # Build the videos that are currently eligible.
            if day_active:
                active_files = [
                    item["filename"]
                    for item in order
                    if item.get("active", True)
                    and (
                        not current_category
                        or current_category in item.get("tags", [])
                    )
                ]
            else:
                active_files = [
                    item["filename"]
                    for item in order
                    if item.get("active", True)
                ]

            if not active_files:
                log(
                    f"No active files for current schedule. "
                    f"schedule_active={day_active}, "
                    f"category={current_category}",
                    "PLAYBACK"
                )
                time.sleep(10)
                continue

            current_video = settings.get(
                "selected_video",
                ""
            )

            # --------------------------------------------------------
            # SCHEDULE ENFORCEMENT
            #
            # If a schedule slot is currently active, its Schedule Tag
            # is authoritative regardless of play mode, interval, or
            # Trigger Change.
            #
            # If the current video is already valid, leave it alone.
            # If it is not valid, immediately select an eligible video.
            # --------------------------------------------------------
            if day_active and current_video not in active_files:
                new_video = active_files[0]

                last_updated_str = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                settings["selected_video"] = new_video
                settings["playlist"]["last_updated"] = (
                    last_updated_str
                )

                save_settings(settings)

                log(
                    f"Schedule enforced: {current_video} -> "
                    f"{new_video} "
                    f"(tag={current_category})",
                    "SCHEDULE"
                )

                notify_selection_sync(new_video)

                time.sleep(1)
                continue

            # --------------------------------------------------------
            # NORMAL PLAYLIST PROCESSING
            #
            # Schedule enforcement above is independent of the
            # playlist interval. Once the current video is valid,
            # the selected play mode and interval control normal
            # playlist changes.
            # --------------------------------------------------------
            if (
                mode not in ["single", "random", "fixed"]
                or interval <= 0
                or trigger_change
            ):
                time.sleep(1)
                continue

            now = datetime.now()

            try:
                last_dt = (
                    datetime.strptime(
                        last_updated,
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if last_updated
                    else None
                )
            except Exception as e:
                log(
                    f"Error parsing last_updated "
                    f"'{last_updated}': {e}",
                    "ERROR"
                )
                last_dt = None

            if (
                not last_dt
                or (now - last_dt) >= timedelta(
                    minutes=interval
                )
            ):
                new_video = current_video

                if mode == "single" or len(active_files) == 1:
                    new_video = active_files[0]

                elif mode == "random":
                    other_choices = [
                        v
                        for v in active_files
                        if v != current_video
                    ]

                    new_video = (
                        random.choice(other_choices)
                        if other_choices
                        else current_video
                    )

                elif mode == "fixed":
                    if current_video in active_files:
                        idx = active_files.index(
                            current_video
                        )

                        new_video = active_files[
                            (idx + 1) % len(active_files)
                        ]
                    else:
                        new_video = active_files[0]

                last_updated_str = now.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                selection_changed = (
                    new_video != current_video
                )

                settings["selected_video"] = new_video
                settings["playlist"]["last_updated"] = (
                    last_updated_str
                )

                save_settings(settings)

                log(
                    f"Mode: {mode}, New video: {new_video}, "
                    f"Updated at: {last_updated_str}",
                    "PLAYBACK"
                )

                if selection_changed:
                    notify_selection_sync(new_video)

        except Exception as e:
            log(
                f"Playlist updater error: "
                f"{type(e).__name__}: {e}",
                "ERROR"
            )

        time.sleep(1)