
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename
from pathlib import Path
import os
from datetime import datetime, timedelta
import random
from flask import jsonify, send_file
import sys
import json
import time
import subprocess
import re
import secrets

HOME = Path(os.path.expanduser("~"))

# Add the shared folder to sys.path
sys.path.append(str(HOME))

from shared.auth_manager import (
    get_or_create_secret_key,
    load_auth_data,
    validate_username,
    validate_password,
    verify_password,
    create_admin,
    update_admin,
    save_auth_data,
)


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
    get_next_start_time,
    get_secondary_video_mode,
    get_time_format,
)

from shared.network import (
    load_network_settings,
    save_network_settings,
    set_role,
    add_secondary,
    update_secondary,
    remove_secondary,
    configure_mosquitto,
    check_secondary_status,
    get_sync_start_delay_ms,
    get_sync_start_lead_ms
)
from shared.system_info import get_system_info
from shared.discovery_service import (
    start_discovery_service,
    get_discovered_secondary_pis,
    verify_secondary_device,
)
from shared.update_helper import check_for_update
from shared.update_manager import start_update
from shared.display_helper import (
    get_display_info,
    apply_display_mode,
    restore_default_display_mode,
)
from shared import mqtt_client
from shared.power_manager import start_power_scheduler

from shared.audio import (
    get_audio_outputs,
    get_effective_audio_output,
    set_audio_output,
    get_audio_output
)

app = Flask(__name__)
app.secret_key = get_or_create_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # The current server is HTTP-only. Enable this when HTTPS is configured.
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_REFRESH_EACH_REQUEST=True,
)
start_power_scheduler()
start_discovery_service()

_LOGIN_FAILURES = {}
_LOGIN_WINDOW_SECONDS = 15 * 60
SESSION_TIMEOUT_OPTIONS = (0.25, 0.5, 1, 4, 8, 12, 24, 48)
_DEFAULT_SESSION_TIMEOUT_HOURS = 8
_LOGIN_MAX_FAILURES = 5


def _csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _get_session_timeout_hours(auth_data=None):
    auth_data = auth_data if isinstance(auth_data, dict) else load_auth_data()
    try:
        timeout_hours = float(auth_data.get("session_timeout_hours", _DEFAULT_SESSION_TIMEOUT_HOURS))
    except (TypeError, ValueError):
        timeout_hours = _DEFAULT_SESSION_TIMEOUT_HOURS
    return timeout_hours if timeout_hours in SESSION_TIMEOUT_OPTIONS else _DEFAULT_SESSION_TIMEOUT_HOURS


@app.context_processor
def inject_auth_template_values():
    return {
        "csrf_token": _csrf_token,
        "session_timeout_hours": _get_session_timeout_hours(),
        "session_timeout_options": SESSION_TIMEOUT_OPTIONS,
    }


@app.before_request
def enforce_authentication_and_csrf():
    # All state-changing requests, including login and setup, require a session token.
    if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
        expected = session.get("_csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        if not expected or not supplied or not secrets.compare_digest(str(expected), str(supplied)):
            return "CSRF validation failed. Reload the page and try again.", 400

    auth_data = load_auth_data()
    configured = bool(auth_data.get("username") and auth_data.get("password"))
    timeout_hours = _get_session_timeout_hours(auth_data)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=timeout_hours)
    endpoint = request.endpoint or ""

    if endpoint in ("static", "login", "admin_setup"):
        if endpoint == "login" and not configured:
            return redirect(url_for("admin_setup"))
        if endpoint == "admin_setup" and configured:
            return redirect(url_for("login"))
        return None

    # The logo is the only image available before login; all other media is private.
    if endpoint == "image_file" and request.view_args and request.view_args.get("filename") == "logo.png":
        return None

    if not configured:
        return redirect(url_for("admin_setup", next=request.path))

    if not session.get("auth_user"):
        return redirect(url_for("login", next=request.path))

    if session.get("auth_version") != auth_data.get("session_version"):
        session.clear()
        flash("Your session has ended because the account credentials changed. Please sign in again.", "warning")
        return redirect(url_for("login"))

    last_activity = session.get("last_activity", 0)
    if not isinstance(last_activity, (int, float)) or time.time() - last_activity > timeout_hours * 60 * 60:
        session.clear()
        flash("Your session expired. Please sign in again.", "warning")
        return redirect(url_for("login"))

    session["last_activity"] = time.time()
    return None


@app.after_request
def add_csrf_tokens_to_forms(response):
    if response.mimetype == "text/html" and response.status_code < 400:
        # Generate a token even on public login/setup pages whose templates do not
        # explicitly call csrf_token(). Flask saves this session after after_request.
        token = _csrf_token()
        html = response.get_data(as_text=True)
        hidden = '<input type="hidden" name="csrf_token" value="' + token + '">'
        html = re.sub(r"(<form\b[^>]*>)", lambda match: match.group(1) + hidden, html, flags=re.IGNORECASE)
        response.set_data(html)
    return response


def _login_is_rate_limited(key):
    now = time.monotonic()
    failures = [stamp for stamp in _LOGIN_FAILURES.get(key, []) if now - stamp < _LOGIN_WINDOW_SECONDS]
    _LOGIN_FAILURES[key] = failures
    return len(failures) >= _LOGIN_MAX_FAILURES


def _record_login_failure(key):
    now = time.monotonic()
    failures = [stamp for stamp in _LOGIN_FAILURES.get(key, []) if now - stamp < _LOGIN_WINDOW_SECONDS]
    failures.append(now)
    _LOGIN_FAILURES[key] = failures


@app.route("/admin-setup", methods=["GET", "POST"])
def admin_setup():
    auth_data = load_auth_data()
    if auth_data.get("username") and auth_data.get("password"):
        return redirect(url_for("login"))

    if request.method == "POST":
        username = validate_username(request.form.get("username", ""))
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")

        if not username:
            flash("Username must be 3–32 characters using letters, numbers, periods, underscores, or hyphens.", "danger")
        elif not validate_password(password):
            flash("Password must be at least 12 characters and have no leading or trailing whitespace.", "danger")
        elif password != confirmation:
            flash("The passwords do not match.", "danger")
        else:
            # Re-check immediately before writing so only one first-run request wins.
            auth_data = load_auth_data()
            if auth_data.get("username") and auth_data.get("password"):
                return redirect(url_for("login"))
            created = create_admin(username, password)
            saved = load_auth_data()
            session.clear()
            session.permanent = True
            session["auth_user"] = saved.get("username", username)
            session["auth_version"] = saved.get("session_version")
            session["last_activity"] = time.time()
            _csrf_token()
            flash("Administrator account created. Complete the LivingPortraitApp setup below.", "success")
            return redirect(url_for("index"))

    return render_template("admin_setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    auth_data = load_auth_data()
    if not auth_data.get("username") or not auth_data.get("password"):
        return redirect(url_for("admin_setup"))

    if (
        request.method == "GET"
        and session.get("auth_user")
        and session.get("auth_version") == auth_data.get("session_version")
    ):
        return redirect(url_for("index"))

    if request.method == "POST":
        remote = request.remote_addr or "unknown"
        key = remote[:128]
        if _login_is_rate_limited(key):
            flash("Too many sign-in attempts. Wait 15 minutes before trying again.", "danger")
            return redirect(url_for("login"))

        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_password(password, auth_data.get("password")) and username.strip().casefold() == str(auth_data.get("username", "")).casefold():
            _LOGIN_FAILURES.pop(key, None)
            session.clear()
            session.permanent = True
            session["auth_user"] = auth_data["username"]
            session["auth_version"] = auth_data.get("session_version")
            session["last_activity"] = time.time()
            _csrf_token()
            return redirect(url_for("index"))

        _record_login_failure(key)
        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/account-session-settings", methods=["POST"])
def account_session_settings():
    auth_data = load_auth_data()
    try:
        timeout_hours = float(request.form.get("session_timeout_hours", ""))
    except (TypeError, ValueError):
        timeout_hours = None

    if timeout_hours not in SESSION_TIMEOUT_OPTIONS:
        flash("Select a valid session timeout.", "danger")
        return redirect(url_for("index") + "#account_security")

    auth_data["session_timeout_hours"] = timeout_hours
    save_auth_data(auth_data)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=timeout_hours)
    session.permanent = True
    session["last_activity"] = time.time()
    flash("Session timeout updated successfully.", "success")
    return redirect(url_for("index") + "#account_security")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/account-security", methods=["POST"])
def account_security():
    auth_data = load_auth_data()
    current_password = request.form.get("current_password", "")
    action = request.form.get("action", "")

    if not verify_password(current_password, auth_data.get("password")):
        flash("The current password is incorrect.", "danger")
        return redirect(url_for("index") + "#account_security")

    if action == "change_username":
        username = validate_username(request.form.get("new_username", ""))
        if not username:
            flash("Username must be 3–32 characters using letters, numbers, periods, underscores, or hyphens.", "danger")
            return redirect(url_for("index") + "#account_security")

        updated = update_admin(username, None)
        session["auth_user"] = updated["username"]
        session["auth_version"] = updated.get("session_version")
        session["last_activity"] = time.time()
        flash("Administrator username updated successfully.", "success")
        return redirect(url_for("index") + "#account_security")

    if action == "change_password":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_new_password", "")

        if new_password != confirm_password:
            flash("The new passwords do not match.", "danger")
            return redirect(url_for("index") + "#account_security")
        if not validate_password(new_password):
            flash("New password must be at least 12 characters and have no leading or trailing whitespace.", "danger")
            return redirect(url_for("index") + "#account_security")

        updated = update_admin(auth_data.get("username", ""), new_password)
        session["auth_user"] = updated["username"]
        session["auth_version"] = updated.get("session_version")
        session["last_activity"] = time.time()
        flash("Administrator password updated successfully.", "success")
        return redirect(url_for("index") + "#account_security")

    flash("Unknown account action. Please try again.", "danger")
    return redirect(url_for("index") + "#account_security")


VIDEO_FOLDER = HOME / "videos"
IMAGES_FOLDER = HOME / "images"
LOG_FOLDER = HOME / "logs"
SETTINGS_FILE = HOME / "settings.json"
MQTT_STATUS_FILE = HOME / "mqtt_status.json"

# Ensure directories exist
LOG_FOLDER.mkdir(parents=True, exist_ok=True)
VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)


def format_ampm(time_str, time_format="12"):
    try:
        if time_format == "24":
            return datetime.strptime(
                time_str,
                "%H:%M"
            ).strftime("%H:%M")

        return datetime.strptime(
            time_str,
            "%H:%M"
        ).strftime("%I:%M %p")

    except (ValueError, TypeError):
        return time_str


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
    settings = load_settings()

    if not settings.get("setup_complete", False):
        return redirect(url_for("setup"))

    time_format = get_time_format()

    if time_format not in ("12", "24"):
        time_format = "12"

    if time_format == "24":
        current_time = datetime.now().strftime(
            "%A %H:%M:%S"
        )
    else:
        current_time = datetime.now().strftime(
            "%A %I:%M:%S %p"
        )

    theme = request.cookies.get("themeMode", "light")
    version = get_version()

    # Check for application updates using the configured update channel.
    update_channel = settings.get("update_channel", "beta")
    update_status = check_for_update(version, update_channel)

    videos = sorted([f.name for f in VIDEO_FOLDER.glob("*.mp4")])

    selected_video = settings.get("selected_video", "")
    pause_flag = settings.get("pause_flag", False)
    reboot_required = session.get("reboot_required", False)
    mute_audio = bool(settings.get("mute_audio", True))
    audio_outputs = get_audio_outputs()
    audio_output = get_effective_audio_output()["id"]


    # Detect current display mode and available HDMI modes.
    try:
        display_info = get_display_info()
    except Exception as e:
        log(f"Error detecting display information: {e}", "ERROR")
        display_info = {
            "current_resolution": None,
            "available_modes": [],
            "available_resolutions": [],
            "connectors": [],
            "detection_method": "unavailable"
        }



    display_mode_selection = settings.get("display_mode_selection")    
    power_schedule = settings.get("power_schedule", {})

    # Master Sync Tags
    sync_tags = settings.get("sync_tags", [])

    # Master Schedule Tags
    schedule_tags = settings.get("schedule_tags", [])

    network_settings = load_network_settings()
    role = network_settings.get("role", "")
    primary_ip = network_settings.get("primary_ip", "")
    enable = network_settings.get("enable", "0")
    sync_start_delay_ms = get_sync_start_delay_ms()
    sync_start_lead_ms = get_sync_start_lead_ms()
    secondary_pis = check_secondary_status()
    discovered_secondary_pis = get_discovered_secondary_pis()
    configured_device_ips = {
        str(pi.get("device_id")): str(pi.get("ip", "")).strip()
        for pi in secondary_pis
        if pi.get("device_id")
    }
    configured_device_ids = set(configured_device_ips)
    configured_ips = {
        str(pi.get("ip", "")).strip()
        for pi in secondary_pis
        if str(pi.get("ip", "")).strip()
    }
    for discovered_pi in discovered_secondary_pis:
        device_id = discovered_pi.get("device_id")
        discovered_ip = str(discovered_pi.get("ip", "")).strip()
        matched_by_id = device_id in configured_device_ids
        matched_by_ip = discovered_ip in configured_ips
        discovered_pi["is_configured"] = matched_by_id or matched_by_ip
        discovered_pi["ip_changed"] = (
            matched_by_id
            and configured_device_ips.get(device_id, "") != discovered_ip
        )
        discovered_pi["needs_link"] = matched_by_ip and not matched_by_id

    # Read MQTT status without importing mqtt_client.
    # This prevents Flask from starting a second MQTT worker.
    mqtt_connected = get_mqtt_status()

    mode, interval, last_updated, order, triggered_flag, delay = get_playlist_settings()
    delay = delay or 0

    playlist_settings = settings.get("playlist", {})

    trigger_change = bool(
        playlist_settings.get("trigger_change", False)
    )

    secondary_start_mode = playlist_settings.get(
        "secondary_start_mode",
        "with_primary"
    )

    secondary_start_delay = playlist_settings.get(
        "secondary_start_delay",
        0
    )

    try:
        secondary_start_delay = int(secondary_start_delay)
    except (ValueError, TypeError):
        secondary_start_delay = 0

    secondary_video_mode = playlist_settings.get(
        "secondary_video_mode",
        "sync_tag"
    )

    if secondary_video_mode not in ("sync_tag", "playlist"):
        secondary_video_mode = "sync_tag"

    # Get days schedule
    days_schedule = settings.get("days", {})

    # Format times for all slots and store in a list
    for day, sched in days_schedule.items():
        slots = []

        for slot_key in ["slot1", "slot2"]:
            slot = sched.get(slot_key, {})

            if slot.get("enabled", False):
                start_time = datetime.strptime(
                    slot.get("start", "00:00"),
                    "%H:%M"
                ).time()

                end_time = datetime.strptime(
                    slot.get("end", "23:59"),
                    "%H:%M"
                ).time()

                now_time = datetime.now().time()
                is_active = start_time <= now_time < end_time

                slots.append({
                    "name": slot_key,
                    "start_ampm": format_ampm(
                        slot.get("start", "00:00"),
                        time_format
                    ),
                    "end_ampm": format_ampm(
                        slot.get("end", "23:59"),
                        time_format
                    ),
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

    # Fixed Playlist Schedule Tag display
    fixed_order_display = []

    active_schedule_tag = None

    for slot in today_schedule.get("slots", []):
        if slot.get("is_active"):
            active_schedule_tag = slot.get("category", "")
            break

    for entry in fixed_order:
        video_tags = entry.get("tags", [])

        plays_now = True

        if active_schedule_tag:
            plays_now = active_schedule_tag in video_tags

        fixed_order_display.append({
            "filename": entry.get("filename", ""),
            "tags": video_tags,
            "plays_now": plays_now
        })


    manage_videos = [
        entry
        for entry in order
        if isinstance(entry, dict)
        and entry.get("filename") in videos
    ]

    manage_videosTags = settings.get(
        "playlist",
        {}
    ).get(
        "order",
        []
    )

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
            last_dt = datetime.strptime(
                last_updated,
                "%Y-%m-%d %H:%M:%S"
            )

            next_dt = last_dt + timedelta(
                seconds=interval * 60
            )

            now = datetime.now()
            diff = (next_dt - now).total_seconds()

            time_remaining = max(
                0,
                int(diff)
            )

        except Exception as e:
            log(
                f"Error calculating time remaining: {e}",
                "ERROR"
            )

    logs = []
    recent_activity = []

    if LOG_FOLDER.exists():
        log_files = list(LOG_FOLDER.glob("*.txt"))

        for f in log_files:
            if time_format == "24":
                log_mtime = datetime.fromtimestamp(
                    f.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M")
            else:
                log_mtime = datetime.fromtimestamp(
                    f.stat().st_mtime
                ).strftime("%Y-%m-%d %I:%M %p")

            logs.append({
                "name": f.name,
                "mtime": log_mtime,
                "size": f.stat().st_size
            })

            try:
                with open(
                    f,
                    "r",
                    errors="replace"
                ) as log_file:

                    for line in log_file:
                        line = line.strip()

                        if not line:
                            continue

                        timestamp = None
                        category = "SYSTEM"
                        message = line

                        if line.startswith("["):
                            first_end = line.find("]")

                            if first_end != -1:
                                timestamp_text = line[1:first_end]

                                try:
                                    timestamp = datetime.fromisoformat(
                                        timestamp_text
                                    )
                                except ValueError:
                                    timestamp = datetime.fromtimestamp(
                                        f.stat().st_mtime
                                    )

                                remainder = line[
                                    first_end + 1:
                                ].strip()

                                if remainder.startswith("["):
                                    category_end = remainder.find("]")

                                    if category_end != -1:
                                        category = remainder[
                                            1:category_end
                                        ]

                                        message = remainder[
                                            category_end + 1:
                                        ].strip()
                                    else:
                                        message = remainder
                                else:
                                    message = remainder

                        if timestamp is None:
                            timestamp = datetime.fromtimestamp(
                                f.stat().st_mtime
                            )

                        if time_format == "24":
                            activity_time = timestamp.strftime(
                                "%H:%M"
                            )
                        else:
                            activity_time = timestamp.strftime(
                                "%I:%M %p"
                            ).lstrip("0")

                        recent_activity.append({
                            "time": activity_time,
                            "category": category,
                            "message": message,
                            "timestamp": timestamp
                        })

            except Exception as e:
                log(
                    f"Error reading recent activity from {f.name}: {e}",
                    "ERROR"
                )

        logs.sort(
            key=lambda x: x["mtime"],
            reverse=True
        )

        recent_activity.sort(
            key=lambda x: x["timestamp"],
            reverse=True
        )

        recent_activity = recent_activity[:8]
        system_info = get_system_info()

    return render_template(
        "index.html",
        auth_username=session.get("auth_user", ""),
        logs=logs,
        recent_activity=recent_activity,
        videos=fixed_order,
        selected=selected_video,
        playlist_mode=mode,
        interval=interval,
        last_updated=last_updated,
        fixed_order=fixed_order,
        fixed_order_display=fixed_order_display,
        manage_videos=manage_videos,
        time_remaining=time_remaining,
        available_tags=available_tags,
        schedule_tags=schedule_tags,
        sync_tags=sync_tags,
        pause=pause_flag,
        video_count=len(fixed_order),
        theme=theme,
        days=days_schedule,
        today_schedule=today_schedule,
        today=today,
        current_time=current_time,
        time_format=time_format,
        is_schedule_enabled_now=schedule_enabled,
        next_start_time=next_start_time,
        next_category=next_category,
        triggered_flag=triggered_flag,
        trigger_change=trigger_change,
        delay=delay,
        secondary_start_mode=secondary_start_mode,
        secondary_start_delay=secondary_start_delay,
        secondary_video_mode=secondary_video_mode,
        role=role,
        primary_ip=primary_ip,
        enable=enable,
        secondary_pis=secondary_pis,
        discovered_secondary_pis=discovered_secondary_pis,
        mqtt_connected=mqtt_connected,
        sync_start_delay_ms=sync_start_delay_ms,
        sync_start_lead_ms=sync_start_lead_ms,
        version=version,
        update_status=update_status,
        reboot_required=reboot_required,
        mute_audio=mute_audio,
        audio_outputs=audio_outputs,
        audio_output=audio_output,
        system_info=system_info,
        display_info=display_info,
        display_mode_selection=display_mode_selection,
        power_schedule=power_schedule
    )


def _get_discovered_secondary_pis_for_config(secondary_pis):
    """Annotate discovered devices with their current configuration state."""
    discovered = get_discovered_secondary_pis()
    configured_device_ips = {
        str(pi.get("device_id")): str(pi.get("ip", "")).strip()
        for pi in secondary_pis if pi.get("device_id")
    }
    configured_device_ids = set(configured_device_ips)
    configured_ips = {str(pi.get("ip", "")).strip() for pi in secondary_pis if str(pi.get("ip", "")).strip()}
    for device in discovered:
        device_id = device.get("device_id")
        ip = str(device.get("ip", "")).strip()
        matched_by_id = device_id in configured_device_ids
        matched_by_ip = ip in configured_ips
        device["is_configured"] = matched_by_id or matched_by_ip
        device["ip_changed"] = matched_by_id and configured_device_ips.get(device_id, "") != ip
        device["needs_link"] = matched_by_ip and not matched_by_id
    return discovered

@app.route("/setup", methods=["GET", "POST"])
def setup():
    settings = load_settings()
    network_settings = load_network_settings()
    videos = sorted([f.name for f in VIDEO_FOLDER.glob("*.mp4")])

    if settings.get("setup_complete", False):
        return redirect(url_for("index"))

    role = request.args.get("role", network_settings.get("role", "secondary"))
    if role not in ("primary", "secondary"):
        role = network_settings.get("role", "secondary")
    enable = network_settings.get("enable", "0")
    primary_ip = network_settings.get("primary_ip", "")
    secondary_pis = network_settings.get("secondary_pis", [])
    discovered_secondary_pis = _get_discovered_secondary_pis_for_config(secondary_pis)
    audio_outputs = get_audio_outputs()
    audio_output = get_audio_output()

    if request.method == "POST":
        role = request.form.get("role", "secondary")
        enable = "1" if request.form.get("enable") == "1" else "0"
        primary_ip = request.form.get("primary_ip", "").strip()
        audio_output = request.form.get("audio_output", "default")

        if role not in ("primary", "secondary"):
            role = "secondary"

        if role == "primary":
            primary_ip = ""

        if role == "secondary" and enable == "1" and not primary_ip:
            flash(
                "Primary Pi IP Address is required when MQTT is enabled on a Secondary.",
                "danger"
            )

            return render_template(
                "setup.html",
                role=role,
                enable=enable,
                primary_ip=primary_ip,
                secondary_pis=secondary_pis,
                    discovered_secondary_pis=discovered_secondary_pis,
                videos=videos,
                audio_outputs=audio_outputs,
                audio_output=audio_output
            )

        # Read Secondary Pis configured on the Primary.
        new_secondary_pis = []
        index = 0

        while True:
            name_key = f"secondary_pis[{index}][name]"
            ip_key = f"secondary_pis[{index}][ip]"

            if name_key not in request.form and ip_key not in request.form:
                break

            name = request.form.get(name_key, "").strip()
            ip = request.form.get(ip_key, "").strip()

            if not name or not ip:
                flash(
                    "Each Secondary Pi must have both a name and IP address.",
                    "danger"
                )

                return render_template(
                    "setup.html",
                    role=role,
                    enable=enable,
                    primary_ip=primary_ip,
                    secondary_pis=new_secondary_pis,
                    discovered_secondary_pis=_get_discovered_secondary_pis_for_config(new_secondary_pis),
                    videos=videos,
                    audio_outputs=audio_outputs,
                    audio_output=audio_output
                )

            new_secondary_pis.append({
                "name": name[:50],
                "ip": ip
            })

            index += 1

        # Save Role / MQTT / Primary IP using the existing network helper.
        set_role(role, primary_ip, enable)

        settings["audio_output"] = audio_output
        save_settings(settings)

        # Save Secondary Pis.
        network_settings = load_network_settings()
        network_settings["secondary_pis"] = new_secondary_pis
        save_network_settings(network_settings)

        # Configure MQTT according to the selected role and setting.
        configure_mosquitto(role, enable)

        # First video upload.
        setup_video = request.files.get("video")

        if not videos and (
            not setup_video or setup_video.filename == ""
        ):
            flash(
                "Please upload at least one MP4 video before completing setup.",
                "danger"
            )

            return render_template(
                "setup.html",
                role=role,
                enable=enable,
                primary_ip=primary_ip,
                secondary_pis=new_secondary_pis,
                    discovered_secondary_pis=_get_discovered_secondary_pis_for_config(new_secondary_pis),
                videos=videos,
                audio_outputs=audio_outputs,
                audio_output=audio_output
            )

        if setup_video and setup_video.filename:
            if not setup_video.filename.lower().endswith(".mp4"):
                flash(
                    "Only .mp4 files are allowed for the initial video.",
                    "danger"
                )

                return render_template(
                    "setup.html",
                    role=role,
                    enable=enable,
                    primary_ip=primary_ip,
                    secondary_pis=new_secondary_pis,
                    discovered_secondary_pis=_get_discovered_secondary_pis_for_config(new_secondary_pis),
                    videos=videos,
                    audio_outputs=audio_outputs,
                    audio_output=audio_output
                )

            filename = secure_filename(setup_video.filename)

            if not filename:
                flash("Invalid video filename.", "danger")

                return render_template(
                    "setup.html",
                    role=role,
                    enable=enable,
                    primary_ip=primary_ip,
                    secondary_pis=new_secondary_pis,
                    discovered_secondary_pis=_get_discovered_secondary_pis_for_config(new_secondary_pis),
                    videos=videos,
                    audio_outputs=audio_outputs,
                    audio_output=audio_output
                )

            save_path = VIDEO_FOLDER / filename
            setup_video.save(save_path)

            settings = load_settings()
            order = settings.get("playlist", {}).get("order", [])

            existing_video = next(
                (
                    item
                    for item in order
                    if item.get("filename") == filename
                ),
                None
            )

            if existing_video:
                existing_video["active"] = True
            else:
                order.append({
                    "filename": filename,
                    "active": True
                })

            settings["playlist"]["order"] = order
            settings["selected_video"] = filename
            settings["pause_flag"] = False
            save_settings(settings)

            videos = sorted([
                f.name
                for f in VIDEO_FOLDER.glob("*.mp4")
            ])

        else:
            settings = load_settings()

            if videos:
                selected_video = settings.get(
                    "selected_video",
                    ""
                )

                if (
                    not selected_video
                    or not (VIDEO_FOLDER / selected_video).exists()
                ):
                    selected_video = videos[0]
                    settings["selected_video"] = selected_video

                settings["pause_flag"] = False
                save_settings(settings)

        settings = load_settings()
        settings["setup_complete"] = True
        save_settings(settings)

        flash(
            "LivingPortraitApp setup completed successfully.",
            "success"
        )

        return redirect(url_for("index"))

    return render_template(
        "setup.html",
        role=role,
        enable=enable,
        primary_ip=primary_ip,
        secondary_pis=secondary_pis,
                    discovered_secondary_pis=_get_discovered_secondary_pis_for_config(secondary_pis),
        videos=videos,
        audio_outputs=audio_outputs,
        audio_output=audio_output
    )


@app.route("/select", methods=["POST"])
def select():
    action = request.form.get("action", "")
    playlist_mode = request.form.get("mode", "")
    interval_str = request.form.get("interval", "0")
    triggered_flag = request.form.get("triggered_flag") == "on"
    trigger_change = request.form.get("trigger_change") == "on"

    try:
        delay = int(request.form.get("delay", 0))
        secondary_start_delay = int(
            request.form.get("secondary_start_delay", 0)
        )

        if delay < 0 or secondary_start_delay < 0:
            raise ValueError()

    except (ValueError, TypeError):
        flash("Invalid delay value", "danger")
        return redirect(url_for("index"))

    secondary_start_mode = request.form.get(
        "secondary_start_mode",
        "with_primary"
    )

    secondary_video_mode = request.form.get(
        "secondary_video_mode",
        "sync_tag"
    )

    if secondary_video_mode not in ("sync_tag", "playlist"):
        secondary_video_mode = "sync_tag"

    try:
        interval = int(interval_str)

        if interval < 0:
            raise ValueError()

    except (ValueError, TypeError):
        flash("Invalid interval value", "danger")
        return redirect(url_for("index"))

    if playlist_mode == "single":
        trigger_change = False
        interval = 0

    elif trigger_change:
        interval = 0

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
            trigger_change=trigger_change,
            delay=delay,
            secondary_start_mode=secondary_start_mode,
            secondary_start_delay=secondary_start_delay,
            secondary_video_mode=secondary_video_mode
        )

        settings = load_settings()

        if new_order:
            settings["selected_video"] = new_order[0]["filename"]
            save_settings(settings)

        flash("Playlist order shuffled!", "success")
        return redirect(url_for("index"))

    videos = sorted([
        f.name
        for f in VIDEO_FOLDER.glob("*.mp4")
    ])

    if not videos:
        flash(
            "No videos found in the Videos folder",
            "danger"
        )
        return redirect(url_for("index"))

    if playlist_mode == "random":
        if not trigger_change and interval == 0:
            flash(
                "Interval must be greater than zero for random mode",
                "danger"
            )
            return redirect(url_for("index"))

        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        update_playlist_settings(
            mode="random",
            interval=interval,
            last_updated=timestamp,
            triggered_flag=triggered_flag,
            trigger_change=trigger_change,
            delay=delay,
            secondary_start_mode=secondary_start_mode,
            secondary_start_delay=secondary_start_delay,
            secondary_video_mode=secondary_video_mode
        )

        settings = load_settings()
        current_video = settings.get(
            "selected_video",
            ""
        )

        order = settings.get(
            "playlist",
            {}
        ).get(
            "order",
            []
        )

        active_files = [
            item["filename"]
            for item in order
            if item.get("active", True)
        ]

        if not active_files:
            flash(
                "No active videos available for random playback",
                "danger"
            )
            return redirect(url_for("index"))

        other_choices = [
            f
            for f in active_files
            if f != current_video
        ]

        new_video = (
            random.choice(other_choices)
            if other_choices
            else current_video
        )

        settings["selected_video"] = new_video
        save_settings(settings)

        if trigger_change:
            flash(
                "Random mode enabled with Trigger Change",
                "success"
            )
        else:
            flash(
                f"Random mode enabled with interval {interval} seconds",
                "success"
            )

    elif playlist_mode == "fixed":
        if not trigger_change and interval == 0:
            flash(
                "Interval must be greater than zero for fixed mode",
                "danger"
            )
            return redirect(url_for("index"))

        order_str = request.form.get(
            "fixed_order",
            ""
        )

        filenames = [
            v.strip()
            for v in order_str.split(",")
            if v.strip() in videos
        ]

        if not filenames:
            flash(
                "Please provide a valid fixed order with existing videos",
                "danger"
            )
            return redirect(url_for("index"))

        existing_order = load_settings().get(
            "playlist",
            {}
        ).get(
            "order",
            []
        )

        existing_dict = {
            entry["filename"]: entry
            for entry in existing_order
            if "filename" in entry
        }

        new_order = []

        for fn in filenames:
            if fn in existing_dict:
                entry = dict(existing_dict[fn])
                entry["active"] = True
                new_order.append(entry)
            else:
                new_order.append({
                    "filename": fn,
                    "active": True
                })

        for fn, entry in existing_dict.items():
            if fn not in filenames:
                entry = dict(entry)
                entry["active"] = False
                new_order.append(entry)

        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        update_playlist_settings(
            mode="fixed",
            interval=interval,
            last_updated=timestamp,
            order=new_order,
            triggered_flag=triggered_flag,
            trigger_change=trigger_change,
            delay=delay,
            secondary_start_mode=secondary_start_mode,
            secondary_start_delay=secondary_start_delay,
            secondary_video_mode=secondary_video_mode
        )

        settings = load_settings()

        if new_order:
            settings["selected_video"] = new_order[0]["filename"]
            save_settings(settings)

        if trigger_change:
            flash(
                "Fixed playlist mode enabled with Trigger Change",
                "success"
            )
        else:
            flash(
                f"Fixed playlist mode enabled with interval {interval} seconds",
                "success"
            )

    else:
        selected_video = request.form.get("video")

        if (
            selected_video
            and (VIDEO_FOLDER / selected_video).exists()
        ):
            settings = load_settings()

            settings["selected_video"] = selected_video
            settings["playlist"]["mode"] = "single"
            settings["playlist"]["interval"] = 0
            settings["playlist"]["last_updated"] = ""
            settings["playlist"]["triggered_flag"] = triggered_flag
            settings["playlist"]["trigger_change"] = False
            settings["playlist"]["delay"] = delay
            settings["playlist"]["secondary_start_mode"] = secondary_start_mode
            settings["playlist"]["secondary_start_delay"] = secondary_start_delay
            settings["playlist"]["secondary_video_mode"] = secondary_video_mode

            save_settings(settings)

            flash(
                f"Selected single video: {selected_video}",
                "success"
            )

        else:
            flash(
                "Invalid video selection",
                "danger"
            )

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
        filename = secure_filename(file.filename)

        if not filename:
            flash("Invalid filename", "danger")
            return redirect(url_for("index"))

        save_path = VIDEO_FOLDER / filename
        file.save(save_path)

        settings = load_settings()
        order = settings.get("playlist", {}).get("order", [])

        if not any(item["filename"] == filename for item in order):
            order.append({
                "filename": filename,
                "active": True
            })
            settings["playlist"]["order"] = order
            save_settings(settings)

        flash(f"Uploaded: {filename}", "success")
    else:
        flash("Only .mp4 files are allowed", "danger")

    return redirect(url_for("index"))

@app.route("/save_schedule", methods=["POST"])
def save_schedule():
    settings = load_settings()
    current_days = settings.get("days", {})
    days = {}

    schedule_tags = settings.get("schedule_tags", [])

    valid_tag_ids = {
        tag.get("id", "").lower()
        for tag in schedule_tags
        if tag.get("id")
    }

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

        if slot1_category and slot1_category.lower() not in valid_tag_ids:
            slot1_category = ""

        # SLOT 2
        slot2_enabled = request.form.get(f"{key}Slot2Enabled") == "on" if day_enabled else False

        slot2_start = request.form.get(f"{key}Slot2Start") or current_days.get(day, {}).get("slot2", {}).get("start", "")
        slot2_end = request.form.get(f"{key}Slot2End") or current_days.get(day, {}).get("slot2", {}).get("end", "")

        if f"{key}Slot2Category" in request.form:
            slot2_category = request.form.get(f"{key}Slot2Category")
        else:
            slot2_category = current_days.get(day, {}).get("slot2", {}).get("category", "")

        if slot2_category and slot2_category.lower() not in valid_tag_ids:
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

        # Per-video audio mute setting.
        # If the checkbox is not checked, it will not be submitted.
        mute_audio = request.form.get(
            f"videos[{index}][mute_audio]"
        ) == "true"

        log(f"{filename} sync_tag = '{sync_tag}'", "SYNC TAGS")

        videos.append({
            "filename": filename,
            "active": active,
            "tags": tags,
            "sync_tag": sync_tag,
            "mute_audio": mute_audio
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

    # Validate schedule categories against the master Schedule Tags.
    valid_schedule_tags = {
        tag.get("id", "").lower()
        for tag in settings.get("schedule_tags", [])
        if tag.get("id")
    }

    for day, sched in settings.get("days", {}).items():
        for slot_name in ["slot1", "slot2"]:
            slot = sched.get(slot_name, {})
            category = slot.get("category", "")

            if category and category.lower() not in valid_schedule_tags:
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

@app.route('/delete/<filename>', methods=['POST'])
def delete(filename):
    filepath = VIDEO_FOLDER / filename

    if not filepath.exists():
        flash('File not found', 'danger')
        return redirect(url_for('index'))

    settings = load_settings()
    playlist = settings.get("playlist", {})
    order = playlist.get("order", [])

    network_settings = load_network_settings()
    role = network_settings.get("role", "primary")
    enable = network_settings.get("enable", "0")
    secondary_video_mode = playlist.get("secondary_video_mode", "sync_tag")

    active_videos = [
        item
        for item in order
        if item.get("active", True)
        and (VIDEO_FOLDER / item.get("filename", "")).is_file()
    ]

    target_entry = next(
        (item for item in order if item.get("filename") == filename),
        None
    )
    target_is_active = target_entry.get("active", True) if target_entry else True

    # Inactive videos can be deleted without affecting the active-video minimum.
    if target_is_active and len(active_videos) <= 1:
        flash("At least one active video must remain.", "danger")
        return redirect(url_for('index'))

    was_selected = Path(settings.get("selected_video", "")).name == filename

    filepath.unlink()

    # Remove from playlist order.
    order = [
        item
        for item in order
        if item["filename"] != filename
    ]

    settings["playlist"]["order"] = order

    selected_name = Path(settings.get("selected_video", "")).name
    if was_selected or not (VIDEO_FOLDER / selected_name).is_file():
        if role == "secondary" and secondary_video_mode == "sync_tag":
            # Let the Primary select the next video by Sync Tag.
            settings["selected_video"] = ""
        else:
            replacement = next(
                (
                    item.get("filename", "")
                    for item in order
                    if item.get("active", True)
                    and item.get("filename")
                    and (VIDEO_FOLDER / item["filename"]).is_file()
                ),
                ""
            )
            settings["selected_video"] = replacement

    save_settings(settings)

    # Check remaining active videos.
    remaining_active = [
        item
        for item in order
        if item.get("active", True) and (VIDEO_FOLDER / item["filename"]).exists()
    ]

    if len(remaining_active) == 1:
        only_video = remaining_active[0]["filename"]

        # Secondary must return to Match Sync Tag when only one active video remains.
        if role == "secondary" and enable == "1":
            update_playlist_settings(
                mode="single",
                interval=0,
                last_updated="",
                secondary_video_mode="sync_tag"
            )
        else:
            update_playlist_settings(
                mode="single",
                interval=0,
                last_updated=""
            )

        settings = load_settings()
        settings["selected_video"] = only_video
        save_settings(settings)

        flash(
            f"Deleted {filename}. Only one active video remains. Switched to single mode with video: {only_video}",
            "info"
        )
    else:
        flash(f"Deleted {filename}", "success")

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
        if not 0 <= sync_start_delay_ms <= 60000:
            raise ValueError("Sync Start Delay must be between 0 and 60000 ms.")

        network_settings = load_network_settings()
        network_settings["sync_start_delay_ms"] = sync_start_delay_ms

        # Save the synchronization lead time only when the Primary form supplies it.
        # Secondary Pis keep their existing setting and never use it for scheduling.
        lead_value = request.form.get("sync_start_lead_ms")
        if role == "primary" and lead_value is not None:
            sync_start_lead_ms = int(lead_value)
            if not 0 <= sync_start_lead_ms <= 5000:
                raise ValueError("Synchronization Lead Time must be between 0 and 5000 ms.")
            network_settings["sync_start_lead_ms"] = sync_start_lead_ms

        save_network_settings(network_settings)

        # Save network role / MQTT settings
        set_role(role, primary_ip, enable)
        configure_mosquitto(role, enable)

        message = "Network settings updated!"

        # Changing role or network configuration requires a reboot
        session["reboot_required"] = True

        # flash(message, "success")
        # flash("Reboot required for network changes to take effect.","danger")

    except Exception as e:
        log(f"Failed to update network: {e}", "ERROR")
        flash(f"Failed to update network: {e}", "danger")

    return redirect(url_for("index"))


@app.route("/reboot", methods=["POST"])
def reboot():
    try:
        log("System reboot requested from Network Settings.", "SYSTEM")
        session["reboot_required"] = False

        subprocess.Popen(
            ["sudo", "/usr/sbin/reboot"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        flash("Rebooting Raspberry Pi...", "warning")

    except Exception as e:
        log(f"Failed to reboot Raspberry Pi: {e}", "ERROR")
        session["reboot_required"] = True
        flash(f"Failed to reboot Raspberry Pi: {e}", "danger")

    return redirect(url_for("index"))

# Add a discovered secondary Pi during initial setup.
@app.route("/setup/add_discovered_secondary", methods=["POST"])
def setup_add_discovered_secondary():
    device_id = request.form.get("device_id", "").strip()
    device = next((item for item in get_discovered_secondary_pis() if item.get("device_id") == device_id), None)
    if not device:
        flash("That device is no longer being discovered. Wait for its next announcement and refresh the page.", "warning")
        return redirect(url_for("setup", role="primary"))
    if not verify_secondary_device(device["ip"], device_id):
        flash("Could not verify a live LivingPortraitApp Secondary at that address. Make sure it is running and on the same local network, then try again.", "warning")
        return redirect(url_for("setup", role="primary"))
    network_settings = load_network_settings()
    secondary_pis = network_settings.get("secondary_pis", [])
    existing = next((item for item in secondary_pis if item.get("device_id") == device_id or str(item.get("ip", "")).strip() == str(device.get("ip", "")).strip()), None)
    if existing:
        same_device = existing.get("device_id") == device_id
        existing["device_id"] = device_id
        if same_device:
            existing["ip"] = device["ip"]
        network_settings["secondary_pis"] = secondary_pis
        save_network_settings(network_settings)
        flash(f"{existing.get('name', device['name'])} is already configured. Device information was refreshed.", "info")
        return redirect(url_for("setup", role="primary"))
    secondary_pis.append({"name": device["name"], "ip": device["ip"], "device_id": device_id})
    network_settings["secondary_pis"] = secondary_pis
    save_network_settings(network_settings)
    log(f"Discovered Secondary Pi added during setup: {device['name']} ({device['ip']})", "NETWORK")
    flash(f"Added Secondary Pi: {device['name']} ({device['ip']}).", "success")
    return redirect(url_for("setup", role="primary"))

# Add a discovered secondary Pi to the configured list.
@app.route("/network/add_discovered_secondary", methods=["POST"])
def network_add_discovered_secondary():
    device_id = request.form.get("device_id", "").strip()
    discovered = get_discovered_secondary_pis()
    device = next(
        (item for item in discovered if item.get("device_id") == device_id),
        None,
    )

    network_settings = load_network_settings()
    if network_settings.get("role") != "primary":
        flash("Only the Primary Pi can add Secondary Pis.", "danger")
        return redirect(url_for("index"))

    if not device:
        flash(
            "That device is no longer being discovered. Wait for its next announcement and refresh the page.",
            "warning",
        )
        return redirect(url_for("index"))

    if not verify_secondary_device(device["ip"], device_id):
        flash(
            "Could not verify a live LivingPortraitApp Secondary at that address. Make sure it is running and on the same local network, then try again.",
            "warning",
        )
        return redirect(url_for("index"))

    secondary_pis = network_settings.get("secondary_pis", [])
    existing = next(
        (
            item for item in secondary_pis
            if item.get("device_id") == device_id
            or str(item.get("ip", "")).strip() == str(device.get("ip", "")).strip()
        ),
        None,
    )

    if existing:
        same_device = existing.get("device_id") == device_id
        existing["device_id"] = device_id
        if same_device:
            existing["ip"] = device["ip"]
        save_network_settings(network_settings)
        flash(
            f"{existing.get('name', device['name'])} is already configured. Device information was refreshed.",
            "info",
        )
        return redirect(url_for("index"))

    secondary_pis.append({
        "name": device["name"],
        "ip": device["ip"],
        "device_id": device_id,
    })
    network_settings["secondary_pis"] = secondary_pis
    save_network_settings(network_settings)
    log(
        f"Discovered Secondary Pi added: {device['name']} ({device['ip']})",
        "NETWORK",
    )
    flash(f"Added Secondary Pi: {device['name']} ({device['ip']}).", "success")
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
        result = check_for_update(installed_version, channel, force_check=True)
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

@app.route("/add_schedule_tag", methods=["POST"])
def add_schedule_tag():
    settings = load_settings()
    schedule_tags = settings.get("schedule_tags", [])

    new_tag = request.form.get("schedule_tag", "").strip()

    if not new_tag:
        flash("Schedule Tag cannot be blank.", "danger")
        return redirect(url_for("index"))

    new_tag = new_tag[:50]

    tag_id = new_tag.lower().strip()
    tag_id = "".join(
        char if char.isalnum() or char in "-_" else "-"
        for char in tag_id
    )

    tag_id = "-".join(
        part for part in tag_id.split("-") if part
    )

    if not tag_id:
        flash("Invalid Schedule Tag name.", "danger")
        return redirect(url_for("index"))

    existing_ids = {
        tag.get("id", "").lower()
        for tag in schedule_tags
    }

    existing_names = {
        tag.get("name", "").lower()
        for tag in schedule_tags
    }

    if tag_id.lower() in existing_ids or new_tag.lower() in existing_names:
        flash(f'Schedule Tag "{new_tag}" already exists.', "warning")
        return redirect(url_for("index"))

    schedule_tags.append({
        "id": tag_id,
        "name": new_tag
    })

    schedule_tags.sort(
        key=lambda tag: tag.get("name", "").lower()
    )

    settings["schedule_tags"] = schedule_tags
    save_settings(settings)

    flash(f'Schedule Tag "{new_tag}" added.', "success")
    return redirect(url_for("index"))

@app.route("/delete_schedule_tag", methods=["POST"])
def delete_schedule_tag():
    settings = load_settings()
    schedule_tags = settings.get("schedule_tags", [])

    tag_to_delete = request.form.get("schedule_tag", "").strip()

    if not tag_to_delete:
        flash("No Schedule Tag was specified.", "danger")
        return redirect(url_for("index"))

    tag_key = tag_to_delete.lower()

    matching_tag = next(
        (
            tag
            for tag in schedule_tags
            if tag.get("id", "").lower() == tag_key
        ),
        None
    )

    if matching_tag is None:
        flash(f'Schedule Tag "{tag_to_delete}" was not found.', "warning")
        return redirect(url_for("index"))

    tag_id = matching_tag.get("id", "")

    order = settings.get("playlist", {}).get("order", [])

    video_count = 0

    for video in order:
        video_tags = video.get("tags", [])

        if any(
            str(video_tag).lower() == tag_id.lower()
            for video_tag in video_tags
        ):
            video_count += 1

    schedule_count = 0

    for day, sched in settings.get("days", {}).items():
        for slot_name in ["slot1", "slot2"]:
            slot = sched.get(slot_name, {})
            category = slot.get("category", "")

            if category and category.lower() == tag_id.lower():
                schedule_count += 1

    if video_count > 0 or schedule_count > 0:
        flash(
            f'Cannot delete Schedule Tag "{matching_tag.get("name", tag_id)}" '
            f'because it is currently in use.',
            "danger"
        )
        return redirect(url_for("index"))

    settings["schedule_tags"] = [
        tag
        for tag in schedule_tags
        if tag.get("id", "").lower() != tag_key
    ]

    save_settings(settings)

    flash(
        f'Schedule Tag "{matching_tag.get("name", tag_id)}" deleted.',
        "success"
    )

    return redirect(url_for("index"))

@app.route("/save_appearance_settings", methods=["POST"])
def save_appearance_settings():
    settings = load_settings()

    settings["mute_audio"] = "mute_audio" in request.form
    settings["audio_output"] = request.form.get("audio_output", "default")
    settings["time_format"] = request.form.get("timeFormat", "12")

    save_settings(settings)

    subprocess.run(
        ["sudo", "systemctl", "restart", "motion_vlc.service"],
        check=False
    )

    flash("Appearance settings saved. Playback restarted.", "success")

    return redirect(url_for("index"))




@app.route("/select_display_mode", methods=["POST"])
def select_display_mode():
    selected_value = request.form.get("display_mode", "").strip()
    log(f"Display mode submitted: {selected_value}", "INFO")

    try:
        if "|" in selected_value:
            width_str, height_str, refresh_str, interlaced_str = selected_value.split("|")
            width = int(width_str)
            height = int(height_str)

            if interlaced_str not in ("0", "1"):
                raise ValueError("Invalid scan type")

            refresh_rate = (
                None
                if refresh_str.lower() in ("none", "unknown")
                else float(refresh_str)
            )
            interlaced = interlaced_str == "1"
        else:
            match = re.fullmatch(
                r"(\d+)x(\d+)@([\d.]+|none|unknown)(i?)",
                selected_value,
                re.IGNORECASE,
            )

            if not match:
                raise ValueError("Invalid display mode format")

            width = int(match.group(1))
            height = int(match.group(2))
            refresh_text = match.group(3)

            refresh_rate = (
                None
                if refresh_text.lower() in ("none", "unknown")
                else float(refresh_text)
            )
            interlaced = match.group(4).lower() == "i"

        display_info = get_display_info()
        log(
            f"Available display modes: {display_info.get('available_modes', [])}",
            "INFO",
        )

        selected_mode = next(
            (
                mode for mode in display_info.get("available_modes", [])
                if mode["width"] == width
                and mode["height"] == height
                and mode.get("interlaced", False) == interlaced
                and (
                    (
                        mode.get("refresh_rate") is None
                        and refresh_rate is None
                    )
                    or (
                        mode.get("refresh_rate") is not None
                        and refresh_rate is not None
                        and abs(mode["refresh_rate"] - refresh_rate) < 0.01
                    )
                )
            ),
            None,
        )

        if selected_mode is None:
            flash("Invalid display mode. Please select a detected mode.", "danger")
            return redirect(url_for("index"))

        if selected_mode.get("refresh_rate") is None:
            flash(
                "This display mode has no detected refresh rate and cannot be applied.",
                "danger",
            )
            return redirect(url_for("index"))

        settings = load_settings()
        previous_selection = settings.get("display_mode_selection")

        new_selection = {
            "width": selected_mode["width"],
            "height": selected_mode["height"],
            "refresh_rate": selected_mode.get("refresh_rate"),
            "interlaced": selected_mode.get("interlaced", False),
            "scan_type": selected_mode.get("scan_type", "progressive"),
            "label": selected_mode["label"],
        }

        # Apply the mode before saving the new selection.
        # If applying fails, the saved selection remains unchanged.
        override = apply_display_mode(new_selection)

        settings["display_mode_selection"] = new_selection

        try:
            save_settings(settings)
        except Exception:
            # Restore the previous boot configuration if settings cannot save.
            try:
                if previous_selection:
                    apply_display_mode(previous_selection)
                else:
                    restore_default_display_mode()
            except Exception as rollback_error:
                log(
                    f"Display configuration rollback failed: {rollback_error}",
                    "ERROR",
                )
            raise

        log(f"Display configuration updated: {override}", "INFO")
        flash(
            f"Display mode saved and applied: {selected_mode['label']}. "
            "Reboot the Raspberry Pi for the change to take effect.",
            "success",
        )

        # Changing role or network configuration requires a reboot
        session["reboot_required"] = True

    except (ValueError, TypeError, KeyError) as e:
        log(f"Invalid display mode selection '{selected_value}': {e}", "ERROR")
        flash(f"Unable to apply the selected display mode: {e}", "danger")

    except Exception as e:
        log(f"Error saving or applying display configuration: {e}", "ERROR")
        flash(
            "Unable to save or apply the display mode. Check the application log.",
            "danger",
        )

    return redirect(url_for("index"))



@app.route("/restore_display_mode", methods=["POST"])
def restore_display_mode():
    try:
        # Restore the default boot display configuration.
        message = restore_default_display_mode()

        # Clear the previously selected custom display mode.
        settings = load_settings()
        previous_selection = settings.pop("display_mode_selection", None)

        try:
            save_settings(settings)
        except Exception:
            # Restore the previous boot configuration if settings cannot save.
            try:
                if previous_selection:
                    apply_display_mode(previous_selection)
            except Exception as rollback_error:
                log(
                    f"Display configuration rollback failed: {rollback_error}",
                    "ERROR",
                )
            raise

        log(f"Display configuration restored: {message}", "INFO")
        flash(
            f"{message} Reboot the Raspberry Pi for the change to take effect.",
            "success",
        )

        session["reboot_required"] = True

    except Exception as e:
        log(f"Error restoring display configuration: {e}", "ERROR")
        flash(
            "Unable to restore the default display configuration. "
            "Check the application log.",
            "danger",
        )

    return redirect(url_for("index"))



@app.route("/power/shutdown", methods=["POST"])
def power_shutdown():
    try:
        log("Manual shutdown requested from Power Management.", "POWER")
        subprocess.Popen(
            ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        flash("Shutting down Raspberry Pi...", "warning")
    except Exception as e:
        log(f"Failed to shut down Raspberry Pi: {e}", "ERROR")
        flash(
            "Unable to shut down Raspberry Pi. Check sudo permissions and logs.",
            "danger",
        )

    return redirect(url_for("index"))


@app.route("/power/schedule", methods=["POST"])
def save_power_schedule():
    enabled = request.form.get("shutdown_enabled") == "1"
    shutdown_time = request.form.get("shutdown_time", "23:00").strip()

    try:
        datetime.strptime(shutdown_time, "%H:%M")
    except ValueError:
        flash("Invalid shutdown time.", "danger")
        return redirect(url_for("index"))

    settings = load_settings()
    schedule = settings.get("power_schedule", {})
    schedule["shutdown_enabled"] = enabled
    schedule["shutdown_time"] = shutdown_time
    settings["power_schedule"] = schedule
    save_settings(settings)

    log(
        f"Automatic shutdown {'enabled' if enabled else 'disabled'}"
        + (f" for {shutdown_time}." if enabled else "."),
        "POWER",
    )

    flash(
        f"Automatic shutdown {'enabled for ' + shutdown_time if enabled else 'disabled'}.",
        "success",
    )

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )