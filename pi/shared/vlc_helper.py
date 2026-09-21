# vlc_helper.py
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

# Thread control
stop_playlist_thread = threading.Event()

def get_version():
    version_file = HOME / "version.txt"
    try:
        with open(version_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "unknown"

VERSION = get_version()

def log(msg):
    timestamp = f"[{datetime.now().isoformat()}]"
    log_line = f"{timestamp} {msg}"
    print(log_line)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_FOLDER / f"{date_str}.txt"
    with log_file.open("a") as f:
        f.write(f"{log_line}\n")

def load_settings():
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
    else:
        settings = {
            "selected_video": "",
            "pause_flag": False,
            "playlist": {
                "mode": "single",
                "interval": 0,
                "last_updated": "",
                "order": [],
                "triggered_flag": True,
                "delay": 0
            }
        }

    # Run migration to ensure slot1/slot2 exist
    settings = migrate_days_slots(settings)
    return settings

def save_settings(settings):
    temp_file = SETTINGS_FILE.with_suffix(".tmp")

    with open(temp_file, 'w') as f:
        json.dump(settings, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp_file, SETTINGS_FILE)

def get_days_schedule():
    settings = load_settings()
    return settings.get("days", {})

def update_days_schedule(days_schedule):
    settings = load_settings()
    settings["days"] = days_schedule
    save_settings(settings)

def migrate_days_slots(settings):
    """
    Ensure that 'days' in settings has slot1 and slot2 for each day.
    Migrates old start/end/category into slot1 if present.
    """
    days = settings.get("days", {})

    for day_name in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
        if day_name not in days:
            days[day_name] = {"enabled": False}

        day = days[day_name]

        # Ensure slot1 exists (migrate old top-level start/end/category)
        if "slot1" not in day:
            day["slot1"] = {
                "enabled": day.get("enabled", False),
                "start": day.get("start", "00:00"),
                "end": day.get("end", "23:59"),
                "category": day.get("category", "")
            }

        # Ensure slot2 exists
        if "slot2" not in day:
            day["slot2"] = {
                "enabled": False,
                "start": "",
                "end": "",
                "category": ""
            }

        # Remove old top-level start/end/category to avoid conflicts
        day.pop("start", None)
        day.pop("end", None)
        day.pop("category", None)

    settings["days"] = days
    return settings


def get_triggered_flag():
    settings = load_settings()
    playlist = settings.get("playlist", {})

    # Default to False if not set
    flag = playlist.get("triggered_flag", False)

    return bool(flag)

def get_trigger_delay_seconds():
    settings = load_settings()
    playlist = settings.get("playlist", {})

    delay = playlist.get("delay", 0)
    try:
        return int(delay)
    except (ValueError, TypeError):
        return 0

from datetime import datetime, timedelta

def is_schedule_enabled_now():
    """
    Returns True if the schedule is active now.
    Checks both slot1 and slot2 for today's schedule.
    """
    settings = load_settings()
    days = settings.get("days", {})

    now = datetime.now()
    current_day = now.strftime("%A")
    now_time = now.time()

    today_schedule = days.get(current_day, {})

    # If no slots are enabled, consider always active
    if not today_schedule.get("slot1", {}).get("enabled", False) and \
       not today_schedule.get("slot2", {}).get("enabled", False):
        return True

    for slot_key in ["slot1", "slot2"]:
        slot = today_schedule.get(slot_key, {})
        if not slot.get("enabled", False):
            continue

        start_str = slot.get("start", "00:00")
        end_str = slot.get("end", "23:59")

        try:
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
        except Exception as e:
            log(f"[Schedule] Failed to parse times for {current_day} {slot_key}: {e}")
            continue

        if start_time <= now_time < end_time:
            return True

    return False


def is_current_schedule_active():
    """
    Returns True if any slot of today's schedule is currently active.
    """
    settings = load_settings()
    days = settings.get("days", {})

    now = datetime.now()
    current_day = now.strftime("%A")
    now_time = now.time()

    today_schedule = days.get(current_day, {})

    for slot_key in ["slot1", "slot2"]:
        slot = today_schedule.get(slot_key, {})
        if not slot.get("enabled", False):
            continue

        start_str = slot.get("start", "00:00")
        end_str = slot.get("end", "23:59")

        try:
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
        except Exception as e:
            log(f"[Schedule] Failed to parse start/end time for {current_day} {slot_key}: {e}")
            continue

        if start_time <= now_time < end_time:
            return True

    return False


def get_next_start_time(settings):
    """
    Returns the earliest upcoming start time (and its category)
    from all enabled slots across the next 7 days.
    """
    days = settings.get("days", {})
    now = datetime.now()
    upcoming_slots = []

    for i in range(7):
        check_date = now.date() + timedelta(days=i)
        day_name = check_date.strftime("%A")
        schedule = days.get(day_name, {})

        for slot_key in ["slot1", "slot2"]:
            slot = schedule.get(slot_key, {})
            if not slot.get("enabled", False):
                continue

            start_str = slot.get("start", "00:00")
            category = slot.get("category")

            try:
                start_time = datetime.strptime(start_str, "%H:%M").time()
                start_dt = datetime.combine(check_date, start_time)
            except Exception as e:
                log(f"[Schedule] Failed to parse start time for {day_name} {slot_key}: {e}")
                continue

            if start_dt > now:
                upcoming_slots.append((start_dt, day_name, category))

    if not upcoming_slots:
        return None, None

    next_start_dt, next_day, next_category = min(upcoming_slots, key=lambda x: x[0])
    return next_start_dt.strftime(f"{next_day} %I:%M %p"), next_category


def get_current_scheduler_category():
    """
    Returns the category/tag of the currently active schedule period.
    Example: "kids", "scary", etc.
    Returns None if no schedule is active.
    """
    settings = load_settings()
    days = settings.get("days", {})
    now = datetime.now()
    current_day = now.strftime("%A")
    now_time = now.time()

    today_schedule = days.get(current_day, {})

    for slot_key in ["slot1", "slot2"]:
        slot = today_schedule.get(slot_key, {})
        if not slot.get("enabled", False):
            continue

        start_str = slot.get("start", "00:00")
        end_str = slot.get("end", "23:59")
        category = slot.get("category", None)

        try:
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
        except Exception as e:
            log(f"[Schedule] Failed to parse start/end time for {current_day} {slot_key}: {e}")
            continue

        if start_time <= now_time < end_time:
            log(f"[Schedule] Active category: {category or 'None'} for {current_day} {slot_key}")
            return category

    return None




def get_playlist_settings():
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

def update_playlist_settings(mode=None, interval=None, last_updated=None, order=None, triggered_flag=None, delay=None):
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
    if delay is not None:
        playlist["delay"] = delay 

    settings["playlist"] = playlist
    save_settings(settings)

def update_playlist_timestamp_on_startup():
    try:
        settings = load_settings()
        playlist = settings.get("playlist", {})
        mode = playlist.get("mode", "single").lower()
        interval = playlist.get("interval", 0)  # interval in minutes
        last_updated_str = playlist.get("last_updated", "")

        if mode not in ("random", "fixed"):
            log(f"[Startup] Playlist mode '{mode}' does not require timestamp update.")
            return

        now = datetime.now()
        last_updated = None
        if last_updated_str:
            try:
                last_updated = datetime.strptime(last_updated_str, "%Y-%m-%d %H:%M:%S")
            except Exception as e:
                log(f"[Startup] Failed to parse last_updated timestamp: {e}")

        # Update only if missing or expired and interval > 0
        if interval > 0 and (not last_updated or (now - last_updated) >= timedelta(minutes=interval)):
            new_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            playlist["last_updated"] = new_timestamp
            settings["playlist"] = playlist
            save_settings(settings)
            log(f"[Startup] Playlist mode '{mode}' detected. Updated last_updated to: {new_timestamp}")
        else:
            log(f"[Startup] Playlist timestamp still valid or interval is zero, no update needed.")

    except Exception as e:
        log(f"Failed to update playlist timestamp: {e}")


def get_selected_video():
    try:
        settings = load_settings()
        selected_name = settings.get("selected_video", "").strip()
        video_path = VIDEO_FOLDER / selected_name
        if video_path.exists():
            return str(video_path)
        else:
            log(f"Selected video {selected_name} not found in folder")
            return None
    except Exception as e:
        log(f"Failed to read selected_video from settings.json: {e}")
        return None

def read_pause_flag():
    try:
        settings = load_settings()
        return settings.get("pause_flag", False)
    except Exception as e:
        log(f"Failed to read pause_flag from settings.json: {e}")
        return False

def write_pause_flag(is_paused):
    settings = load_settings()
    settings["pause_flag"] = is_paused
    save_settings(settings)

def playlist_updater():
    while not stop_playlist_thread.is_set():
        try:
            # Get playlist settings
            mode, interval, last_updated, order, triggered_flag, delay = get_playlist_settings()
            pause_flag = read_pause_flag()
            schedule_enabled = is_schedule_enabled_now()
            day_active = is_current_schedule_active()


            # Skip if not relevant
            if mode not in ["single", "random", "fixed"] or interval <= 0 or pause_flag or not schedule_enabled:
                #log(f"[SKIP] mode={mode}, interval={interval}, pause={pause_flag}")
                time.sleep(5)
                continue

            # Determine active videos based on schedule
            if day_active:
                current_category = get_current_scheduler_category()
                active_files = [
                    v["filename"] for v in order
                    if v.get("active", True) and (not current_category or current_category in v.get("tags", []))]
            else:
                active_files = [item["filename"] for item in order if item.get("active", True)]

            #log(f"[DEBUG] Mode={mode}, Pause={pause_flag}, Schedule={day_active}, ActiveFiles={active_files}, LastUpdated={last_updated}")
   

            if not active_files:
                log(f"[SKIP] No active files. schedule_enabled={schedule_enabled}")
                time.sleep(10)
                continue

            settings = load_settings()
            current_video = settings.get("selected_video", "")
            now = datetime.now()


            # Parse last_updated timestamp
            try:
                last_dt = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S") if last_updated else None
            except Exception as e:
                log(f"[Playlist updater] Error parsing last_updated '{last_updated}': {e}")
                last_dt = None

            # Only update if interval has passed
            if not last_dt or (now - last_dt) >= timedelta(minutes=interval):
                new_video = current_video

                # Single mode or only one active video → always pick the single video
                if mode == "single" or len(active_files) == 1:
                    new_video = active_files[0]
                else:
                    if mode == "random":
                        # Pick random different from current
                        other_choices = [v for v in active_files if v != current_video]
                        new_video = random.choice(other_choices) if other_choices else current_video
                    elif mode == "fixed":
                        if current_video in active_files:
                            idx = active_files.index(current_video)
                            new_video = active_files[(idx + 1) % len(active_files)]
                        else:
                            new_video = active_files[0]

                # Save new video and update last_updated timestamp
                last_updated_str = now.strftime("%Y-%m-%d %H:%M:%S")
                settings["selected_video"] = new_video
                settings["playlist"]["last_updated"] = last_updated_str
                save_settings(settings)
                log(f"[Playlist updater] Mode: {mode}, New video: {new_video}, Updated at: {last_updated_str}")

        except Exception as e:
            log(f"[Playlist updater ERROR] {type(e).__name__}: {e}")

        time.sleep(1)
