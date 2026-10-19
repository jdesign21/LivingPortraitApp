"""Local-network discovery for LivingPortraitApp secondary Pis.

Discovery announcements are intended for convenience, not authentication.
Do not use an announcement alone to grant security privileges.
"""
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path

from shared.network import get_role
from shared.vlc_helper import get_version, log

HOME = Path.home()
DISCOVERY_DIR = HOME / ".livingportrait_discovery"
DEVICE_ID_FILE = DISCOVERY_DIR / "device_id"
DISCOVERY_FILE = DISCOVERY_DIR / "discovered_secondary_pis.json"

DISCOVERY_PORT = 37020
ANNOUNCE_INTERVAL_SECONDS = 8
STALE_AFTER_SECONDS = 35
APPLICATION_NAME = "LivingPortraitApp"
PROTOCOL_VERSION = 1

_started = False
_start_lock = threading.Lock()
_file_lock = threading.Lock()


def _ensure_directory():
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DISCOVERY_DIR, 0o700)
    except OSError:
        pass


def get_device_id():
    """Return a stable UUID for this installation, creating it when needed."""
    _ensure_directory()

    try:
        device_id = DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
        return str(uuid.UUID(device_id))
    except (OSError, ValueError, AttributeError):
        device_id = str(uuid.uuid4())
        temporary_file = DEVICE_ID_FILE.with_suffix(".tmp")
        temporary_file.write_text(device_id + "\n", encoding="utf-8")
        try:
            os.chmod(temporary_file, 0o600)
        except OSError:
            pass
        temporary_file.replace(DEVICE_ID_FILE)
        try:
            os.chmod(DEVICE_ID_FILE, 0o600)
        except OSError:
            pass
        return device_id


def _read_discovery_file():
    try:
        data = json.loads(DISCOVERY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return []


def _write_discovery_file(devices):
    _ensure_directory()
    temporary_file = DISCOVERY_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps(devices, indent=2),
        encoding="utf-8"
    )
    try:
        os.chmod(temporary_file, 0o600)
    except OSError:
        pass
    temporary_file.replace(DISCOVERY_FILE)
    try:
        os.chmod(DISCOVERY_FILE, 0o600)
    except OSError:
        pass


def get_discovered_secondary_pis():
    """Return recent secondary announcements, newest first."""
    now = time.time()
    cutoff = now - STALE_AFTER_SECONDS

    with _file_lock:
        stored_devices = _read_discovery_file()

    devices = []
    for device in stored_devices:
        if not isinstance(device, dict):
            continue

        try:
            last_seen = float(device.get("last_seen", 0))
        except (TypeError, ValueError):
            continue

        if last_seen < cutoff:
            continue

        elapsed = max(0, int(now - last_seen))
        if elapsed < 2:
            last_seen_label = "Just now"
        else:
            last_seen_label = f"{elapsed} seconds ago"

        result = dict(device)
        result["last_seen_label"] = last_seen_label
        result["status"] = "online"
        devices.append(result)

    devices.sort(key=lambda item: (str(item.get("name", "")).lower(), str(item.get("ip", ""))))
    return devices


def _handle_announcement(payload, source_ip):
    if not isinstance(payload, dict):
        return
    if payload.get("application") != APPLICATION_NAME:
        return
    if payload.get("message_type") != "announcement":
        return
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        return
    if payload.get("role") != "secondary":
        return

    try:
        device_id = str(uuid.UUID(str(payload.get("device_id", ""))))
    except (ValueError, AttributeError, TypeError):
        return

    name = str(payload.get("name", "")).strip()[:64]
    version = str(payload.get("version", "unknown")).strip()[:40] or "unknown"
    if not name or not source_ip or source_ip == "127.0.0.1":
        return

    now = time.time()
    with _file_lock:
        current = {}
        for item in _read_discovery_file():
            if not isinstance(item, dict):
                continue
            try:
                last_seen = float(item.get("last_seen", 0))
            except (TypeError, ValueError):
                continue
            if now - last_seen <= STALE_AFTER_SECONDS * 2:
                existing_id = item.get("device_id")
                if existing_id:
                    current[str(existing_id)] = item

        current[device_id] = {
            "application": APPLICATION_NAME,
            "role": "secondary",
            "device_id": device_id,
            "name": name,
            "ip": source_ip,
            "version": version,
            "last_seen": now,
        }
        _write_discovery_file(list(current.values()))


def _build_announcement():
    return {
        "application": APPLICATION_NAME,
        "message_type": "announcement",
        "protocol_version": PROTOCOL_VERSION,
        "role": "secondary",
        "device_id": get_device_id(),
        "name": socket.gethostname()[:64],
        "version": get_version()[:40],
        "timestamp": time.time(),
    }


def _announce_forever():
    log("LivingPortraitApp secondary discovery announcements started.", "NETWORK")

    while get_role() == "secondary":
        try:
            payload = json.dumps(_build_announcement()).encode("utf-8")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
        except Exception as exc:
            log(f"Secondary discovery announcement failed: {exc}", "NETWORK")

        time.sleep(ANNOUNCE_INTERVAL_SECONDS)


def _listen_forever():
    while get_role() == "primary":
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(2)
            log(
                f"LivingPortraitApp discovery listener started on UDP {DISCOVERY_PORT}.",
                "NETWORK"
            )

            while get_role() == "primary":
                try:
                    raw_payload, address = sock.recvfrom(4096)
                except socket.timeout:
                    continue

                try:
                    payload = json.loads(raw_payload.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue

                _handle_announcement(payload, address[0])

        except Exception as exc:
            log(f"Primary discovery listener error: {exc}", "NETWORK")
            time.sleep(5)
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


def _discovery_worker():
    while True:
        try:
            role = get_role()
            if role == "primary":
                _listen_forever()
            elif role == "secondary":
                _announce_forever()
            else:
                time.sleep(5)
        except Exception as exc:
            log(f"Discovery service error: {exc}", "NETWORK")
            time.sleep(5)


def start_discovery_service():
    """Start the role-aware discovery service once in this process."""
    global _started

    with _start_lock:
        if _started:
            return
        worker = threading.Thread(
            target=_discovery_worker,
            name="livingportrait-discovery",
            daemon=True,
        )
        worker.start()
        _started = True
