# vlc_network_helper.py
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

HOME = Path(os.path.expanduser("~"))
NETWORK_FILE = HOME / "network_pis.json"

# ----------------------
# Load / Save
# ----------------------
def load_network_settings():
    if NETWORK_FILE.exists():
        with open(NETWORK_FILE, "r") as f:
            return json.load(f)

    return {
        "role": "primary",
        "primary_ip": "",
        "enable": "1",
        "sync_start_delay_ms": 1000,
        "secondary_pis": []
    }


def save_network_settings(settings):
    with open(NETWORK_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ----------------------
# Role / Enable
# ----------------------
def set_role(role, primary_ip="", enable="1"):
    if role not in ["primary", "secondary"]:
        raise ValueError("Role must be 'primary' or 'secondary'")

    settings = load_network_settings()

    settings["role"] = role
    settings["primary_ip"] = primary_ip
    settings["enable"] = enable

    save_network_settings(settings)


def set_enable(enable="1"):
    settings = load_network_settings()
    settings["enable"] = enable
    save_network_settings(settings)


def is_enabled():
    settings = load_network_settings()
    return settings.get("enable", "0") == "1"


# ----------------------
# Secondary Pis
# ----------------------
def add_secondary(name, ip):
    settings = load_network_settings()

    settings["secondary_pis"].append({
        "name": name,
        "ip": ip
    })

    save_network_settings(settings)


def update_secondary(index, name=None, ip=None):
    settings = load_network_settings()

    if 0 <= index < len(settings["secondary_pis"]):
        if name is not None:
            settings["secondary_pis"][index]["name"] = name

        if ip is not None:
            settings["secondary_pis"][index]["ip"] = ip

        save_network_settings(settings)

    else:
        raise IndexError("Secondary index out of range")


def remove_secondary(index):
    settings = load_network_settings()

    if 0 <= index < len(settings["secondary_pis"]):
        settings["secondary_pis"].pop(index)
        save_network_settings(settings)

    else:
        raise IndexError("Secondary index out of range")


def get_secondary_ips():
    settings = load_network_settings()
    return [
        entry["ip"]
        for entry in settings.get("secondary_pis", [])
    ]


def get_primary_ip():
    settings = load_network_settings()
    return settings.get("primary_ip", "")


def get_role():
    settings = load_network_settings()
    return settings.get("role", "primary")

def get_sync_start_delay_ms():
    settings = load_network_settings()
    return int(settings.get("sync_start_delay_ms", 1000))

# ----------------------
# Check Secondary Status
# ----------------------
def check_secondary_status():
    settings = load_network_settings()
    current_time = datetime.now().strftime("%m/%d/%Y %I:%M %p")

    for pi in settings.get("secondary_pis", []):
        ip = pi.get("ip", "").strip()

        if not ip:
            pi["status"] = "offline"
            pi["last_checked"] = current_time
            continue

        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", ip],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2
            )

            if result.returncode == 0:
                pi["status"] = "online"
            else:
                pi["status"] = "offline"

        except (subprocess.TimeoutExpired, OSError):
            pi["status"] = "offline"

        pi["last_checked"] = current_time

    save_network_settings(settings)

    return settings.get("secondary_pis", [])


# ----------------------
# Mosquitto Service
# ----------------------
def configure_mosquitto(role, enable):
    if enable == "1":

        if role == "primary":

            subprocess.run(
                ["sudo", "systemctl", "enable", "mosquitto"],
                check=True
            )

            # Restart so any MQTT listener configuration changes
            # are loaded immediately.
            subprocess.run(
                ["sudo", "systemctl", "restart", "mosquitto"],
                check=True
            )

        elif role == "secondary":

            subprocess.run(
                ["sudo", "systemctl", "disable", "mosquitto"],
                check=True
            )

            subprocess.run(
                ["sudo", "systemctl", "stop", "mosquitto"],
                check=True
            )

        else:
            raise ValueError("Role must be 'primary' or 'secondary'")

    else:

        subprocess.run(
            ["sudo", "systemctl", "disable", "mosquitto"],
            check=True
        )

        subprocess.run(
            ["sudo", "systemctl", "stop", "mosquitto"],
            check=True
        )
