from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from pathlib import Path
import os
from datetime import datetime, timedelta
import random
from flask import jsonify, send_file
import sys
import json
import mqtt_client
import time

HOME = Path(os.path.expanduser("~"))

# Add the shared folder to sys.path
sys.path.append(str(HOME))

from shared.vlc_helper import (
    log,
    get_version,
    load_settings,
    save_settings,
    get_playlist_settings,
    update_playlist_settings,
    read_pause_flag,
    write_pause_flag,
    get_days_schedule,
    update_days_schedule,
    is_schedule_enabled_now,
    get_next_start_time
)

from shared.vlc_network_helper import (
    load_network_settings,
    save_network_settings,
    set_role,
    add_secondary,
    update_secondary,
    remove_secondary,
    configure_mosquitto,
    check_secondary_status,
    get_sync_start_delay_ms
)

from shared.update_helper import check_for_update
from shared.update_manager import start_update

app = Flask(__name__)
app.secret_key = 'replace-this-with-a-secure-random-key'

VIDEO_FOLDER = HOME / "videos"
IMAGES_FOLDER = HOME / "images"
LOG_FOLDER = HOME / "logs"
SETTINGS_FILE = HOME / "settings.json"
MQTT_STATUS_FILE = HOME / "mqtt_status.json"

# Ensure directories exist
LOG_FOLDER.mkdir(parents=True, exist_ok=True)
VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)

def format_ampm(time_str):
    return datetime.strptime(time_str, "%H:%M").strftime("%I:%M %p")

def get_mqtt_status():
    """
    Read the MQTT connection status written by mqtt_client.py.
    Flask only reads this file and does not start an MQTT connection.
    """
    try:
        if not MQTT_STATUS_FILE.exists():
            return False
        with open(MQTT_STATUS_FILE, "r") as f:
            status = json.load(f)
        return status.get("connected", False) is True
    except Exception as e:
        log(f"Error reading MQTT status: {e}", "ERROR")
        return False

@app.route("/")
def index():
    current_time = datetime.now().strftime("%A %I:%M:%S %p")
    theme = request.cookies.get("themeMode", "light")
    version = get_version()
    videos = sorted([f.name for f in VIDEO_FOLDER.glob("*.mp4")])
    settings = load_settings()

    selected_video = settings.get("selected_video", "")
    pause_flag = settings.get("pause_flag", False)

    # Master Sync Tags
    sync_tags = settings.get("sync_tags", [])

    network_settings = load_network_settings()
    role = network_settings.get("role", "")
    primary_ip = network_settings.get("primary_ip", "")
    enable = network_settings.get("enable", "0")
    sync_start_delay_ms = get_sync_start_delay_ms()
    #secondary_pis = network_settings.get("secondary_pis", [])
    secondary_pis = check_secondary_status()

    # Read MQTT status without importing mqtt_client.
    # This prevents Flask from starting a second MQTT worker.
    mqtt_connected = get_mqtt_status()

    mode, interval, last_updated, order, triggered_flag, delay = get_playlist_settings()
    delay = delay or 0

    # Get days schedule
    days_schedule = settings.get("days", {})

    # Format times for all slots and store in a list
    for day, sched in days_schedule.items():
        slots = []
        for slot_key in ["slot1", "slot2"]:
            slot = sched.get(slot_key, {})
            if slot.get("enabled", False):
                start_time = datetime.strptime(slot.get("start", "00:00"), "%H:%M").time()
                end_time = datetime.strptime(slot.get("end", "23:59"), "%H:%M").time()
                now_time = datetime.now().time()
                is_active = start_time <= now_time < end_time
                slots.append({
                    "name": slot_key,
                    "start_ampm": format_ampm(slot.get("start", "00:00")),
                    "end_ampm": format_ampm(slot.get("end", "23:59")),
                    "category": slot.get("category", ""),
                    "is_active": is_active
                })
        sched["slots"] = slots

    # Get today's name
    today = datetime.now().strftime("%A")
    today_schedule = days_schedule.get(today, {})

    # Check if schedule is enabled right now
    schedule_enabled = is_schedule_enabled_now()
    next_start_time, next_category = get_next_start_time(settings)

    fixed_order = [
        entry
        for entry in order
        if isinstance(entry, dict)
        and entry.get("filename") in videos
        and entry.get("active")
    ]

    manage_videos = [
        entry
        for entry in order
        if isinstance(entry, dict)
        and entry.get("filename") in videos
    ]

    manage_videosTags = settings.get("playlist", {}).get("order", [])
    available_tags = set()

    for video in manage_videosTags:
        if not video.get("active", False):
            continue
        for tag in video.get("tags", []):
            available_tags.add(tag.lower())

    available_tags = list(available_tags)

    # Calculate time remaining until next video switch
    time_remaining = None

    if mode in ["random", "fixed"] and last_updated and interval > 0:
        try:
            last_dt = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
            next_dt = last_dt + timedelta(seconds=interval * 60)
            now = datetime.now()
            diff = (next_dt - now).total_seconds()
            time_remaining = max(0, int(diff))
        except Exception as e:
            log(f"Error calculating time remaining: {e}", "ERROR")

    logs = []

    if LOG_FOLDER.exists():
        for f in LOG_FOLDER.glob("*.txt"):
            logs.append({
                "name": f.name,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %I:%M %p"),
                "size": f.stat().st_size
            })
        logs.sort(key=lambda x: x["mtime"], reverse=True)

    return render_template(
        "index.html",
        logs=logs,
        videos=fixed_order,
        selected=selected_video,
        playlist_mode=mode,
        interval=interval,
        last_updated=last_updated,
        fixed_order=fixed_order,
        manage_videos=manage_videos,
        time_remaining=time_remaining,
        available_tags=available_tags,
        sync_tags=sync_tags,
        pause=pause_flag,
        video_count=len(fixed_order),
        theme=theme,
        days=days_schedule,
        today_schedule=today_schedule,
        today=today,
        current_time=current_time,
        is_schedule_enabled_now=schedule_enabled,
        next_start_time=next_start_time,
        next_category=next_category,
        triggered_flag=triggered_flag,
        delay=delay,
        role=role,
        primary_ip=primary_ip,
        enable=enable,
        secondary_pis=secondary_pis,
        mqtt_connected=mqtt_connected,
        sync_start_delay_ms=sync_start_delay_ms,
        version=version
    )

@app.route("/select", methods=["POST"])
def select():
    action = request.form.get("action", "")
    playlist_mode = request.form.get("mode", "")
    interval_str = request.form.get("interval", "0")
    triggered_flag = request.form.get("triggered_flag") == "on"
    delay = int(request.form.get("delay", 0))

    try:
        interval = int(interval_str)
        if interval < 0:
            raise ValueError()
    except (ValueError, TypeError):
        flash("Invalid interval value", "danger")
        return redirect(url_for("index"))

    if action == "shuffle":
        settings = load_settings()
        order = settings.get("playlist", {}).get("order", [])

        active_videos = [
            v
            for v in order
            if v.get("active", True)
        ]

        inactive_videos = [
            v
            for v in order
            if not v.get("active", True)
        ]

        random.shuffle(active_videos)
        new_order = active_videos + inactive_videos
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        update_playlist_settings(
            mode="fixed",
            interval=interval,
            last_updated=timestamp,
            order=new_order,
            triggered_flag=triggered_flag,
            delay=delay
        )

        settings = load_settings()

        if new_order:
            settings["selected_video"] = new_order[0]["filename"]
            save_settings(settings)

        flash("Playlist order shuffled!", "success")
        return redirect(url_for("index"))

    videos = sorted([f.name for f in VIDEO_FOLDER.glob("*.mp4")])

    if not videos:
        flash("No videos found in the Videos folder", "danger")
        return redirect(url_for("index"))

    if playlist_mode == "random":
        if interval == 0:
            flash("Interval must be greater than zero for random mode", "danger")
            return redirect(url_for("index"))

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        update_playlist_settings(
            mode="random",
            interval=interval,
            last_updated=timestamp,
            triggered_flag=triggered_flag,
            delay=delay
        )

        settings = load_settings()
        current_video = settings.get("selected_video", "")
        order = settings.get("playlist", {}).get("order", [])

        active_files = [
            item["filename"]
            for item in order
            if item.get("active", True)
        ]

        if not active_files:
            flash("No active videos available for random playback", "danger")
            return redirect(url_for("index"))

        other_choices = [
            f
            for f in active_files
            if f != current_video
        ]

        new_video = random.choice(other_choices) if other_choices else current_video
        settings["selected_video"] = new_video
        save_settings(settings)

        flash(f"Random mode enabled with interval {interval} seconds", "success")

    elif playlist_mode == "fixed":
        if interval == 0:
            flash("Interval must be greater than zero for fixed mode", "danger")
            return redirect(url_for("index"))

        order_str = request.form.get("fixed_order", "")

        filenames = [
            v.strip()
            for v in order_str.split(",")
            if v.strip() in videos
        ]

        if not filenames:
            flash("Please provide a valid fixed order with existing videos", "danger")
            return redirect(url_for("index"))

        existing_order = load_settings().get("playlist", {}).get("order", [])

        existing_dict = {
            entry["filename"]: entry
            for entry in existing_order
            if "filename" in entry
        }

        new_order = []

        for fn in filenames:
            new_order.append({
                "filename": fn,
                "active": True
            })

        for fn, entry in existing_dict.items():
            if fn not in filenames:
                new_order.append({
                    "filename": fn,
                    "active": False
                })

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        update_playlist_settings(
            mode="fixed",
            interval=interval,
            last_updated=timestamp,
            order=new_order,
            triggered_flag=triggered_flag,
            delay=delay
        )

        settings = load_settings()

        if new_order:
            settings["selected_video"] = new_order[0]["filename"]
            save_settings(settings)

        flash(f"Fixed playlist mode enabled with interval {interval} seconds", "success")

    else:
        selected_video = request.form.get("video")

        if selected_video and (VIDEO_FOLDER / selected_video).exists():
            settings = load_settings()
            settings["selected_video"] = selected_video
            settings["playlist"]["mode"] = "single"
            settings["playlist"]["interval"] = 0
            settings["playlist"]["last_updated"] = ""
            settings["playlist"]["triggered_flag"] = triggered_flag
            settings["playlist"]["delay"] = delay
            save_settings(settings)

            flash(f"Selected single video: {selected_video}", "success")
        else:
            flash("Invalid video selection", "danger")

    return redirect(url_for("index"))

@app.route("/pause_toggle", methods=["POST"])
def pause_toggle():
    pause = request.form.get("pause")
    is_paused = pause == "on"
    write_pause_flag(is_paused)
    return redirect(url_for("index"))

@app.route("/videos/<filename>")
def video_file(filename):
    full_path = VIDEO_FOLDER / filename

    if not full_path.exists():
        log("Video file does not exist.", "VIDEO")
        return "File not found", 404

    return send_from_directory(VIDEO_FOLDER, filename)

@app.route("/images/<filename>")
def image_file(filename):
    full_path = IMAGES_FOLDER / filename

    if not full_path.exists():
        log("Image file does not exist.", "ERROR")
        return "File not found", 404

    return send_from_directory(IMAGES_FOLDER, filename)

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        flash("No file part", "danger")
        return redirect(url_for("index"))

    file = request.files["file"]

    if file.filename == "":
        flash("No selected file", "danger")
        return redirect(url_for("index"))

    if file and file.filename.lower().endswith(".mp4"):
        save_path = VIDEO_FOLDER / file.filename
        file.save(save_path)

        settings = load_settings()
        order = settings.get("playlist", {}).get("order", [])

        if not any(item["filename"] == file.filename for item in order):
            order.append({
                "filename": file.filename,
                "active": True
            })
            settings["playlist"]["order"] = order
            save_settings(settings)

        flash(f"Uploaded: {file.filename}", "success")
    else:
        flash("Only .mp4 files are allowed", "danger")

    return redirect(url_for("index"))

@app.route("/save_schedule", methods=["POST"])
def save_schedule():
    settings = load_settings()
    current_days = settings.get("days", {})
    days = {}

    manage_videosTags = settings.get("playlist", {}).get("order", [])
    available_tags = set()

    for video in manage_videosTags:
        if not video.get("active", False):
            continue
        for tag in video.get("tags", []):
            available_tags.add(tag.lower())

    available_tags = list(available_tags)

    for day in [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday"
    ]:
        key = day.lower()
        day_enabled = True

        # SLOT 1
        slot1_enabled = request.form.get(f"{key}Slot1Enabled") == "on" if day_enabled else False

        slot1_start = request.form.get(f"{key}Slot1Start") or current_days.get(day, {}).get("slot1", {}).get("start", "00:00")
        slot1_end = request.form.get(f"{key}Slot1End") or current_days.get(day, {}).get("slot1", {}).get("end", "23:59")

        if f"{key}Slot1Category" in request.form:
            slot1_category = request.form.get(f"{key}Slot1Category")
        else:
            slot1_category = current_days.get(day, {}).get("slot1", {}).get("category", "")

        if slot1_category and slot1_category.lower() not in available_tags:
            slot1_category = ""

        # SLOT 2
        slot2_enabled = request.form.get(f"{key}Slot2Enabled") == "on" if day_enabled else False

        slot2_start = request.form.get(f"{key}Slot2Start") or current_days.get(day, {}).get("slot2", {}).get("start", "")
        slot2_end = request.form.get(f"{key}Slot2End") or current_days.get(day, {}).get("slot2", {}).get("end", "")

        if f"{key}Slot2Category" in request.form:
            slot2_category = request.form.get(f"{key}Slot2Category")
        else:
            slot2_category = current_days.get(day, {}).get("slot2", {}).get("category", "")

        if slot2_category and slot2_category.lower() not in available_tags:
            slot2_category = ""

        days[day] = {
            "enabled": day_enabled,
            "slot1": {
                "enabled": slot1_enabled,
                "start": slot1_start,
                "end": slot1_end,
                "category": slot1_category
            },
            "slot2": {
                "enabled": slot2_enabled,
                "start": slot2_start,
                "end": slot2_end,
                "category": slot2_category
            }
        }

    settings["days"] = days
    save_settings(settings)

    flash("Schedule saved successfully!", "success")
    return redirect(url_for("index"))

@app.route("/update_all", methods=["POST"])
def update_all():
    settings = load_settings()
    order = settings.get("playlist", {}).get("order", [])
    videos_form = request.form.to_dict(flat=False)

    videos = []
    index = 0

    while f"videos[{index}][filename]" in request.form:
        filename = request.form.get(f"videos[{index}][filename]")
        active = request.form.get(f"videos[{index}][active]") == "true"
        tags = request.form.getlist(f"videos[{index}][tags][]")

        # Sync Tag is optional.
        # Existing videos without a sync_tag will simply use "".
        sync_tag = request.form.get(f"videos[{index}][sync_tag]", "").strip()

        log(f"{filename} sync_tag = '{sync_tag}'", "SYNC TAGS")

        videos.append({
            "filename": filename,
            "active": active,
            "tags": tags,
            "sync_tag": sync_tag
        })

        index += 1

    active_videos = [
        v
        for v in videos
        if v["active"]
    ]

    if len(active_videos) == 0:
        flash("At least one video must remain active.", "danger")
        return redirect(url_for("index"))

    # Make sure each Sync Tag is only assigned to one video.
    sync_tag_videos = {}

    for video in videos:
        sync_tag = video.get("sync_tag", "")

        if sync_tag:
            sync_tag_key = sync_tag.lower()

            if sync_tag_key in sync_tag_videos:
                flash(
                    f'Sync Tag "{sync_tag}" is already assigned to '
                    f'"{sync_tag_videos[sync_tag_key]}". It cannot also be assigned '
                    f'to "{video["filename"]}".',
                    "danger"
                )
                return redirect(url_for("index"))

            sync_tag_videos[sync_tag_key] = video["filename"]

    for video in videos:
        existing = next(
            (
                v
                for v in order
                if v["filename"] == video["filename"]
            ),
            None
        )

        if existing:
            existing.update(video)
        else:
            order.append(video)

    settings["playlist"]["order"] = order

    active_tags = set()

    for v in order:
        if v.get("active", True):
            for tag in v.get("tags", []):
                active_tags.add(tag.lower())

    for day, sched in settings.get("days", {}).items():
        for slot_name in ["slot1", "slot2"]:
            slot = sched.get(slot_name, {})
            category = slot.get("category", "")

            if category and category.lower() not in active_tags:
                slot["category"] = ""

    save_settings(settings)

    if len(active_videos) == 1:
        only_video = active_videos[0]["filename"]

        update_playlist_settings(
            mode="single",
            interval=0,
            last_updated=""
        )

        settings = load_settings()
        settings["selected_video"] = only_video
        save_settings(settings)

        flash(
            f"Only one active video remains. "
            f"Switched to single mode with video: {only_video}",
            "info"
        )
    else:
        flash("All videos updated successfully.", "success")

    return redirect(url_for("index"))

@app.route("/add_sync_tag", methods=["POST"])
def add_sync_tag():
    """
    Add a new Sync Tag to the Primary master list.
    """
    settings = load_settings()
    sync_tags = settings.get("sync_tags", [])

    new_tag = request.form.get("sync_tag", "").strip()

    if not new_tag:
        flash("Sync Tag cannot be blank.", "danger")
        return redirect(url_for("index"))

    # Enforce maximum length.
    new_tag = new_tag[:50]

    # Sync Tags are case-insensitive.
    existing_tags_lower = {
        tag.lower()
        for tag in sync_tags
    }

    if new_tag.lower() in existing_tags_lower:
        flash(f'Sync Tag "{new_tag}" already exists.', "warning")
        return redirect(url_for("index"))

    sync_tags.append(new_tag)

    # Keep the master list sorted.
    sync_tags.sort(key=lambda tag: tag.lower())

    settings["sync_tags"] = sync_tags
    save_settings(settings)

    flash(f'Sync Tag "{new_tag}" added.', "success")
    return redirect(url_for("index"))

@app.route("/delete_sync_tag", methods=["POST"])
def delete_sync_tag():
    """
    Delete a Sync Tag from the Primary master list.

    Any video currently assigned to the deleted tag will have
    its sync_tag cleared so there are no orphaned assignments.
    """
    settings = load_settings()
    sync_tags = settings.get("sync_tags", [])

    tag_to_delete = request.form.get("sync_tag", "").strip()

    if not tag_to_delete:
        flash("No Sync Tag was specified.", "danger")
        return redirect(url_for("index"))

    tag_key = tag_to_delete.lower()

    # Find the actual stored tag so we preserve its casing.
    matching_tag = next(
        (
            tag
            for tag in sync_tags
            if tag.lower() == tag_key
        ),
        None
    )

    if matching_tag is None:
        flash(f'Sync Tag "{tag_to_delete}" was not found.', "warning")
        return redirect(url_for("index"))

    # Remove the tag from the master list.
    settings["sync_tags"] = [
        tag
        for tag in sync_tags
        if tag.lower() != tag_key
    ]

    # Remove the deleted Sync Tag from any local video assignment.
    order = settings.get("playlist", {}).get("order", [])
    assignments_removed = 0

    for video in order:
        video_sync_tag = video.get("sync_tag", "").strip()

        if video_sync_tag and video_sync_tag.lower() == tag_key:
            video["sync_tag"] = ""
            assignments_removed += 1

    settings["playlist"]["order"] = order
    save_settings(settings)

    if assignments_removed:
        flash(
            f'Sync Tag "{matching_tag}" deleted and removed '
            f'from {assignments_removed} video assignment(s).',
            "success"
        )
    else:
        flash(f'Sync Tag "{matching_tag}" deleted.', "success")

    return redirect(url_for("index"))

@app.route("/sync_tags_to_secondaries", methods=["POST"])
def sync_tags_to_secondaries():
    """
    Send the Primary Sync Tag list to all Secondary Pis
    and report the result for each configured Secondary.
    """
    settings = load_settings()
    sync_tags = settings.get("sync_tags", [])

    network_settings = load_network_settings()
    secondary_pis = network_settings.get("secondary_pis", [])

    # Clear acknowledgments from any previous sync.
    mqtt_client.clear_sync_tag_acknowledgments()

    # Send the complete Sync Tag list.
    mqtt_client.publish(
        mqtt_client.TOPIC_CONTROL,
        {
            "command": "sync_tags",
            "sync_tags": sync_tags
        }
    )

    # Give Secondaries time to receive, process, and acknowledge.
    time.sleep(2)

    acknowledgments = mqtt_client.get_sync_tag_acknowledgments()

    # Check every configured Secondary.
    if not secondary_pis:
        flash("No Secondary Pis are configured.", "warning")
        return redirect(url_for("index"))

    for secondary in secondary_pis:
        secondary_name = secondary.get("name", "Unknown")
        secondary_ip = secondary.get("ip", "").strip()

        if not secondary_ip:
            flash(
                f"{secondary_name} — No IP address configured.",
                "danger"
            )
            continue

        result = acknowledgments.get(secondary_ip)

        if result is None:
            flash(
                f"{secondary_name} — {secondary_ip} — No response",
                "danger"
            )
            continue

        if result.get("success"):
            flash(
                f"{secondary_name} — {secondary_ip} — Sync successful",
                "success"
            )
        else:
            message = result.get("message", "Unknown error")
            flash(
                f"{secondary_name} — {secondary_ip} — "
                f"Sync failed: {message}",
                "danger"
            )

    return redirect(url_for("index"))

@app.route("/delete/<filename>", methods=["POST"])
def delete(filename):
    filepath = VIDEO_FOLDER / filename

    if filepath.exists():
        filepath.unlink()

        settings = load_settings()
        order = settings.get("playlist", {}).get("order", [])

        order = [
            item
            for item in order
            if item["filename"] != filename
        ]

        settings["playlist"]["order"] = order
        save_settings(settings)

        flash(f"Deleted {filename}", "success")
    else:
        flash("File not found", "danger")

    return redirect(url_for("index"))

@app.route("/logs/view/<filename>")
def view_log(filename):
    safe_filename = os.path.basename(filename)
    filepath = LOG_FOLDER / safe_filename

    if not filepath.exists() or not filepath.is_file():
        flash("Log file not found", "danger")
        return redirect(url_for("index"))

    try:
        with open(filepath, "r") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(max(0, file_size - 20000))
            content = f.read()
    except Exception as e:
        log(f"Error reading log file {safe_filename}: {e}", "ERROR")
        flash(f"Error reading file: {e}", "danger")
        return redirect(url_for("index"))

    return render_template(
        "view_log.html",
        filename=safe_filename,
        content=content
    )

@app.route("/logs/raw/<filename>")
def get_log_content(filename):
    safe_filename = os.path.basename(filename)
    filepath = LOG_FOLDER / safe_filename

    if not filepath.exists() or not filepath.is_file():
        return "File not found", 404

    try:
        with open(filepath, "r") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(max(0, file_size - 20000))
            content = f.read()
        return content, 200, {"Content-Type": "text/plain"}
    except Exception as e:
        log(f"Error reading log file {safe_filename}: {e}", "ERROR")
        return f"Error reading log: {e}", 500

@app.route("/logs/delete/<filename>", methods=["POST"])
def delete_log(filename):
    safe_filename = os.path.basename(filename)
    filepath = LOG_FOLDER / safe_filename

    if filepath.exists():
        filepath.unlink()
        log(f"Deleted log {safe_filename}", "SYSTEM")
        flash(f"Deleted log {safe_filename}", "success")
    else:
        log(f"Log file not found: {safe_filename}", "ERROR")
        flash("Log file not found", "danger")

    return redirect(url_for("index"))

@app.route("/logs/download/<filename>")
def download_log(filename):
    safe_filename = os.path.basename(filename)
    filepath = LOG_FOLDER / safe_filename

    if not filepath.exists() or not filepath.is_file():
        log(f"Log file not found for download: {safe_filename}", "ERROR")
        flash("Log file not found", "danger")
        return redirect(url_for("index"))

    return send_file(
        filepath,
        as_attachment=True,
        download_name=safe_filename
    )

@app.route("/network", methods=["POST"])
def network():
    role = request.form.get("role", "primary")
    primary_ip = request.form.get("primary_ip", "")
    enable = request.form.get("enable", "0")

    try:
        # Save Sync Start Delay
        sync_start_delay_ms = int(request.form.get("sync_start_delay_ms", "1000"))

        if sync_start_delay_ms < 0:
            raise ValueError("Sync Start Delay cannot be negative.")

        network_settings = load_network_settings()
        network_settings["sync_start_delay_ms"] = sync_start_delay_ms
        save_network_settings(network_settings)

        # Save network role / MQTT settings
        set_role(role, primary_ip, enable)
        configure_mosquitto(role, enable)

        message = "Network settings updated!"
        reboot_required = False

        # Force Single mode for:
        # - Secondary
        # - Primary with MQTT enabled
        if role == "secondary" or (role == "primary" and enable == "1"):
            settings = load_settings()
            order = settings.get("playlist", {}).get("order", [])

            active_videos = [
                v
                for v in order
                if v.get("active", True)
            ]

            log(f"active_videos: {active_videos}", "PLAYBACK")

            if active_videos:
                only_video = active_videos[0]["filename"]

                update_playlist_settings(
                    mode="single",
                    interval=0,
                    last_updated="",
                    triggered_flag=settings.get("playlist", {}).get("triggered_flag", False),
                    delay=settings.get("playlist", {}).get("delay", 0)
                )

                settings = load_settings()
                settings["selected_video"] = only_video
                save_settings(settings)

                message += f" Switched to single mode with video: {only_video}"

        # Changing role or network configuration requires a reboot
        reboot_required = True

        flash(message, "success")

        if reboot_required:
            flash(
                "Reboot required for network changes to take effect.",
                "danger"
            )

    except Exception as e:
        log(f"Failed to update network: {e}", "ERROR")
        flash(f"Failed to update network: {e}", "danger")

    return redirect(url_for("index"))

# Add a new secondary Pi
@app.route("/network/add_secondary", methods=["POST"])
def network_add_secondary():
    name = request.form.get("name", "").strip()
    ip = request.form.get("ip", "").strip()

    if name and ip:
        add_secondary(name, ip)
        log(f"Added secondary Pi: {name} ({ip})", "NETWORK")
        flash(
            f"Added secondary Pi: {name} ({ip})",
            "success"
        )
    else:
        log("Secondary Pi name and IP are required.", "ERROR")
        flash("Name and IP required", "danger")

    return redirect(url_for("index"))

# Edit an existing secondary Pi
@app.route("/network/edit_secondary/<int:index>", methods=["POST"])
def network_edit_secondary(index):
    name = request.form.get("name", "").strip()
    ip = request.form.get("ip", "").strip()

    try:
        update_secondary(index, name, ip)
        log(f"Updated secondary Pi #{index + 1}", "NETWORK")
        flash(
            f"Updated secondary Pi #{index + 1}",
            "success"
        )
    except IndexError:
        log(f"Invalid secondary Pi index: {index}", "ERROR")
        flash("Invalid secondary index", "danger")

    return redirect(url_for("index"))

# Delete a secondary Pi
@app.route("/network/delete_secondary/<int:index>", methods=["POST"])
def network_delete_secondary(index):
    try:
        remove_secondary(index)
        log(f"Deleted secondary Pi #{index + 1}", "NETWORK")
        flash(
            f"Deleted secondary Pi #{index + 1}",
            "success"
        )
    except IndexError:
        log(f"Invalid secondary Pi index: {index}", "ERROR")
        flash("Invalid secondary index", "danger")

    return redirect(url_for("index"))

# Check Secondary Pi status
@app.route("/network/check_secondary", methods=["POST"])
def network_check_secondary():
    try:
        check_secondary_status()
        log("Secondary Pi status checked.", "NETWORK")
        flash(
            "Secondary Pi status checked.",
            "success"
        )
    except Exception as e:
        log(f"Failed to check Secondary Pi status: {e}", "ERROR")
        flash(
            f"Failed to check Secondary Pi status: {e}",
            "danger"
        )

    return redirect(url_for("index"))

@app.route("/check_updates")
def check_updates():
    channel = request.args.get("channel", "stable").lower()

    if channel not in ("stable", "beta"):
        return jsonify({
            "success": False,
            "error": "Invalid release channel."
        }), 400

    try:
        installed_version = get_version()
        result = check_for_update(installed_version, channel)
        result["success"] = True
        return jsonify(result)
    except Exception as e:
        log(f"Update check failed: {e}", "ERROR")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/start_update", methods=["POST"])
def start_update_route():
    try:
        data = request.get_json(silent=True) or {}
        tag_name = data.get("tag_name", "").strip()

        if not tag_name:
            return jsonify({
                "success": False,
                "error": "No release was specified."
            }), 400

        start_update(tag_name)
        log(f"Update started for release {tag_name}", "UPDATE")

        return jsonify({
            "success": True,
            "message": f"Update to {tag_name} started."
        })
    except Exception as e:
        log(f"Failed to start update: {e}", "ERROR")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/update_status")
def update_status():
    status_file = HOME / "update_status.json"

    if not status_file.exists():
        return jsonify({
            "status": "idle",
            "message": "No update is running.",
            "error": False
        })

    try:
        with open(status_file, "r") as f:
            return jsonify(json.load(f))
    except Exception as e:
        log(f"Failed to read update status: {e}", "ERROR")
        return jsonify({
            "status": "error",
            "message": str(e),
            "error": True
        })

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )