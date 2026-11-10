"""Opt-in, privacy-conscious analytics for LivingPortraitApp."""
import json
import os
import platform
import re
import secrets
import threading
import urllib.request
import uuid
from pathlib import Path

ANALYTICS_HOST = "https://us.i.posthog.com"
ANALYTICS_PROJECT_KEY = "phc_oXP8g4LwrCzPiPQ9WpxaNHfQgEzFyKkKFV88PtHxhDNh"
CONSENT_VERSION = 1
APP_NAME = "LivingPortraitApp"
PRIVATE_DIR = Path.home() / ".livingportrait_auth"
SETTINGS_FILE = PRIVATE_DIR / "analytics.json"
CONTACT_FILE = PRIVATE_DIR / "analytics-contact-email.txt"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_EMAIL_IN_TEXT_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PATH_RE = re.compile(r"(?:/(?:home|Users|mnt|media|var|tmp|opt|etc|srv)/[^\s]+|[A-Z]:\\[^\s]+)")
_FILENAME_RE = re.compile(r"\b[\w .-]+\.(?:mp4|mkv|avi|mov|jpg|jpeg|png|gif|wav|mp3|json|log|py|sh|txt)\b", re.IGNORECASE)
_SECRET_RE = re.compile(r"(?i)(token|password|secret|authorization|username|user)\s*[:=]\s*\S+")


def _ensure_private_dir():
    PRIVATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        PRIVATE_DIR.chmod(0o700)
    except OSError:
        pass


def _write_private(path, text):
    _ensure_private_dir()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    os.replace(temp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _read_settings():
    _ensure_private_dir()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError):
        # An unreadable/corrupt consent file must never enable analytics.
        return {}


def _save_settings(data):
    _write_private(SETTINGS_FILE, json.dumps(data, indent=2) + "\n")


def get_consent_status():
    data = _read_settings()
    current = data.get("consent_version") == CONSENT_VERSION and data.get("decided") is True
    if not current and data.get("consent_version") not in (None, CONSENT_VERSION):
        # A new disclosure version requires a fresh decision; do not carry an
        # old diagnostic contact address into the newly reviewed consent.
        remove_contact_email()
    return {
        "decided": current,
        "enabled": bool(data.get("enabled")) if current else False,
        "consent_required": not current,
    }


def _installation_id(data):
    value = data.get("distinct_id")
    if not isinstance(value, str) or len(value) < 20:
        value = str(uuid.uuid4())
        data["distinct_id"] = value
        _save_settings(data)
    return value


def _app_version():
    try:
        version_file = Path(__file__).resolve().parents[1] / "version.txt"
        return version_file.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _base_properties():
    return {
        "app_name": APP_NAME,
        "app_version": _app_version(),
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "$process_person_profile": False,
        "$geoip_disable": True,
    }


def capture_event(event, properties=None, diagnostic=False):
    """Send one event only after explicit consent; failures never affect the app."""
    try:
        data = _read_settings()
        if data.get("consent_version") != CONSENT_VERSION or data.get("decided") is not True or data.get("enabled") is not True:
            return False

        payload_properties = _base_properties()
        if isinstance(properties, dict):
            payload_properties.update(properties)

        if diagnostic:
            try:
                email = CONTACT_FILE.read_text(encoding="utf-8").strip()
                if email and _EMAIL_RE.fullmatch(email):
                    payload_properties["diagnostic_contact_email"] = email
            except OSError:
                pass

        payload = {
            "api_key": ANALYTICS_PROJECT_KEY,
            "event": str(event)[:100],
            "distinct_id": _installation_id(data),
            "properties": payload_properties,
        }
        request = urllib.request.Request(
            ANALYTICS_HOST + "/capture/",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def save_consent(enabled):
    data = _read_settings()
    if enabled:
        if not isinstance(data.get("distinct_id"), str) or len(data.get("distinct_id", "")) < 20:
            data["distinct_id"] = str(uuid.uuid4())
    else:
        data["distinct_id"] = None
    data.update({
        "decided": True,
        "enabled": bool(enabled),
        "consent_version": CONSENT_VERSION,
    })
    _save_settings(data)
    if not enabled:
        remove_contact_email()
    else:
        threading.Thread(target=capture_event, args=("analytics_enabled",), daemon=True).start()
    return get_consent_status()


def get_contact_email():
    if not get_consent_status()["enabled"]:
        return ""
    try:
        return CONTACT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_contact_email(email):
    if not isinstance(email, str):
        raise ValueError("Enter a valid email address.")
    email = email.strip()
    if not get_consent_status()["enabled"]:
        raise ValueError("Enable Usage Analytics before saving a diagnostic contact email.")
    if not email or len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise ValueError("Enter a valid email address.")
    # Stored locally with owner-only permissions. This is file-permission
    # protection, not encryption; the UI disclosure states that explicitly.
    _write_private(CONTACT_FILE, email + "\n")
    return True


def remove_contact_email():
    try:
        CONTACT_FILE.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def sanitize_error(error):
    value = str(error or "")
    value = _URL_RE.sub("[url]", value)
    value = _EMAIL_IN_TEXT_RE.sub("[email]", value)
    value = _IP_RE.sub("[ip]", value)
    value = _PATH_RE.sub("[path]", value)
    value = _FILENAME_RE.sub("[file]", value)
    value = _SECRET_RE.sub(r"\1=[redacted]", value)
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return " ".join(value.split())[:400]


def capture_diagnostic(error_type, message):
    # Keep the event name stable; the exception class is only a bounded property.
    return capture_event(
        "application_uncaught_exception",
        {"error_type": str(error_type)[:100], "error_message": sanitize_error(message)},
        diagnostic=True,
    )


def capture_application_started():
    return capture_event("application_started")
