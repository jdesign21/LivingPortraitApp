# vlc_network_helper.py
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime
from shared.vlc_helper import log

HOME = Path(os.path.expanduser("~"))
NETWORK_FILE = HOME / "network_pis.json"

def load_network_settings():
    if NETWORK_FILE.exists():
        try:
            with open(NETWORK_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            log(f"Failed to load network settings: {e}", "ERROR")
            raise
    settings = {
        "role": "primary",
        "primary_ip": "",
        "enable": "0",
        "sync_start_delay_ms": 1000,
        "secondary_pis": []
    }
    save_network_settings(settings)
    log("Created default network settings.", "NETWORK")
    return settings

def save_network_settings(settings):
    try:
        with open(NETWORK_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        log(f"Failed to save network settings: {e}", "ERROR")
        raise

def set_role(role, primary_ip="", enable="1"):
    if role not in ["primary", "secondary"]:
        log(f"Invalid network role: {role}", "ERROR")
        raise ValueError("Role must be 'primary' or 'secondary'")
    settings = load_network_settings()
    settings["role"] = role
    settings["primary_ip"] = primary_ip
    settings["enable"] = enable
    save_network_settings(settings)
    log(f"Network role set to {role}. Primary IP: {primary_ip or 'None'}", "NETWORK")

def set_enable(enable="1"):
    settings = load_network_settings()
    settings["enable"] = enable
    save_network_settings(settings)
    log(f"Network synchronization {'enabled' if enable == '1' else 'disabled'}.", "NETWORK")

def is_enabled():
    settings = load_network_settings()
    return settings.get("enable", "0") == "1"

def add_secondary(name, ip):
    settings = load_network_settings()
    settings["secondary_pis"].append({
        "name": name,
        "ip": ip
    })
    save_network_settings(settings)
    log(f"Secondary Pi added: {name} ({ip})", "NETWORK")

def update_secondary(index, name=None, ip=None):
    settings = load_network_settings()
    if 0 <= index < len(settings["secondary_pis"]):
        if name is not None:
            settings["secondary_pis"][index]["name"] = name
        if ip is not None:
            settings["secondary_pis"][index]["ip"] = ip
        save_network_settings(settings)
        log(f"Secondary Pi updated: {name or 'Unknown'} ({ip or 'Unknown'})", "NETWORK")
    else:
        log(f"Secondary index out of range: {index}", "ERROR")
        raise IndexError("Secondary index out of range")

def remove_secondary(index):
    settings = load_network_settings()
    if 0 <= index < len(settings["secondary_pis"]):
        removed = settings["secondary_pis"].pop(index)
        save_network_settings(settings)
        log(f"Secondary Pi removed: {removed.get('name', 'Unknown')} ({removed.get('ip', 'Unknown')})", "NETWORK")
    else:
        log(f"Secondary index out of range: {index}", "ERROR")
        raise IndexError("Secondary index out of range")

def get_secondary_ips():
    settings = load_network_settings()
    return [entry["ip"] for entry in settings.get("secondary_pis", [])]

def get_primary_ip():
    settings = load_network_settings()
    return settings.get("primary_ip", "")

def get_role():
    settings = load_network_settings()
    return settings.get("role", "primary")

def get_sync_start_delay_ms():
    settings = load_network_settings()
    try:
        return int(settings.get("sync_start_delay_ms", 1000))
    except (TypeError, ValueError):
        log("Invalid sync start delay setting. Using 1000 ms.", "ERROR")
        return 1000

def check_secondary_status():
    settings = load_network_settings()
    current_time = datetime.now().strftime("%m/%d/%Y %I:%M %p")

    for pi in settings.get("secondary_pis", []):
        name = pi.get("name", "Unknown")
        ip = pi.get("ip", "").strip()

        if not ip:
            pi["status"] = "offline"
            pi["last_checked"] = current_time
            log(f"Secondary Pi {name} has no IP address.", "NETWORK")
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
                log(f"Secondary Pi {name} ({ip}) is online.", "NETWORK")
            else:
                pi["status"] = "offline"
                log(f"Secondary Pi {name} ({ip}) is offline.", "NETWORK")

        except (subprocess.TimeoutExpired, OSError) as e:
            pi["status"] = "offline"
            log(f"Unable to check Secondary Pi {name} ({ip}): {e}", "NETWORK")

        pi["last_checked"] = current_time

    save_network_settings(settings)
    return settings.get("secondary_pis", [])

def configure_mosquitto(role, enable):
    try:
        if enable == "1":
            if role == "primary":
                subprocess.run(["sudo", "systemctl", "enable", "mosquitto"], check=True)
                subprocess.run(["sudo", "systemctl", "restart", "mosquitto"], check=True)
                log("Mosquitto enabled and restarted on Primary.", "MQTT")
            elif role == "secondary":
                subprocess.run(["sudo", "systemctl", "disable", "mosquitto"], check=True)
                subprocess.run(["sudo", "systemctl", "stop", "mosquitto"], check=True)
                log("Mosquitto disabled and stopped on Secondary.", "MQTT")
            else:
                log(f"Invalid network role for Mosquitto: {role}", "ERROR")
                raise ValueError("Role must be 'primary' or 'secondary'")
        else:
            subprocess.run(["sudo", "systemctl", "disable", "mosquitto"], check=True)
            subprocess.run(["sudo", "systemctl", "stop", "mosquitto"], check=True)
            log("Mosquitto disabled and stopped.", "MQTT")
    except Exception as e:
        log(f"Failed to configure Mosquitto: {e}", "ERROR")
        raise