import json
import re
import subprocess
from pathlib import Path

HOME = Path.home()
SETTINGS_FILE = HOME / "settings.json"
DEFAULT_AUDIO_OUTPUT = "default"


def _load_settings():
    try:
        if not SETTINGS_FILE.exists():
            return {}
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception:
        return False


def get_audio_output():
    """Return the currently selected audio output."""
    settings = _load_settings()
    value = settings.get("audio_output", DEFAULT_AUDIO_OUTPUT)

    if not isinstance(value, str) or not value:
        return DEFAULT_AUDIO_OUTPUT

    return value


def set_audio_output(audio_output):
    """Save the selected audio output."""
    if not isinstance(audio_output, str) or not audio_output:
        audio_output = DEFAULT_AUDIO_OUTPUT

    settings = _load_settings()
    settings["audio_output"] = audio_output
    return _save_settings(settings)


def _get_alsa_playback_devices():
    """Return ALSA playback hardware devices from aplay -l."""
    try:
        result = subprocess.run(
            ["aplay", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )

        if result.returncode != 0:
            return []

        devices = []

        for line in result.stdout.splitlines():
            line = line.strip()

            match = re.match(
                r"^card\s+(\d+):\s+([^\[]+)\[([^\]]+)\],\s+device\s+(\d+):\s+([^\[]+)\[([^\]]+)\]",
                line
            )

            if not match:
                continue

            devices.append({
                "card_number": match.group(1),
                "card_id": match.group(2).strip(),
                "card_name": match.group(3).strip(),
                "device_number": match.group(4),
                "device_id": match.group(5).strip(),
                "device_name": match.group(6).strip()
            })

        return devices

    except Exception:
        return []


def _get_alsa_device_list():
    """Return ALSA PCM device names from aplay -L."""
    try:
        result = subprocess.run(
            ["aplay", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )

        if result.returncode != 0:
            return []

        devices = []
        current_device = None
        current_description = []

        for line in result.stdout.splitlines():
            if line and not line.startswith(" "):
                if current_device:
                    devices.append({
                        "name": current_device,
                        "description": " ".join(current_description)
                    })

                current_device = line.strip()
                current_description = []
            elif line.strip():
                current_description.append(line.strip())

        if current_device:
            devices.append({
                "name": current_device,
                "description": " ".join(current_description)
            })

        return devices

    except Exception:
        return []


def _find_default_card_device(card_id, alsa_devices):
    """Find default:CARD=<card_id>."""
    target = f"default:CARD={card_id}"

    for device in alsa_devices:
        if device["name"] == target:
            return target

    return None


def _find_hdmi_device(card_id, alsa_devices):
    """Find an HDMI ALSA device."""
    prefix = f"hdmi:CARD={card_id},"

    for device in alsa_devices:
        if device["name"].startswith(prefix):
            return device["name"]

    return None


def _is_usb_audio_card(card_id, alsa_devices):
    """Determine whether an ALSA card is a USB audio device."""
    default_name = f"default:CARD={card_id}"

    for device in alsa_devices:
        if device["name"] != default_name:
            continue

        description = device["description"].lower()

        if "usb audio" in description or "usb" in description:
            return True

    return False


def get_audio_outputs():
    """
    Detect available audio outputs.

    Returns:
        id
        name
        type
        alsa_device
    """
    hardware = _get_alsa_playback_devices()
    alsa_devices = _get_alsa_device_list()

    outputs = [
        {
            "id": "default",
            "name": "System Default",
            "type": "default",
            "alsa_device": "default"
        }
    ]

    headphone_found = False
    hdmi_found = False
    usb_cards = set()

    for device in hardware:
        card_id = device["card_id"]
        card_name = device["card_name"]
        device_id = device["device_id"]
        device_name = device["device_name"]

        card_text = (
            f"{card_id} "
            f"{card_name} "
            f"{device_id} "
            f"{device_name}"
        ).lower()

        if "headphone" in card_text and not headphone_found:
            alsa_device = _find_default_card_device(
                card_id,
                alsa_devices
            )

            if alsa_device:
                outputs.append({
                    "id": "headphones",
                    "name": "Headphone Jack",
                    "type": "headphones",
                    "alsa_device": alsa_device
                })
                headphone_found = True

        if "hdmi" in card_text and not hdmi_found:
            alsa_device = _find_hdmi_device(
                card_id,
                alsa_devices
            )

            if alsa_device:
                outputs.append({
                    "id": "hdmi",
                    "name": "HDMI",
                    "type": "hdmi",
                    "alsa_device": alsa_device
                })
                hdmi_found = True

        if _is_usb_audio_card(card_id, alsa_devices):
            alsa_device = _find_default_card_device(
                card_id,
                alsa_devices
            )

            if alsa_device:
                usb_key = f"usb:{card_id}"

                if usb_key not in usb_cards:
                    usb_cards.add(usb_key)

                    outputs.append({
                        "id": usb_key,
                        "name": f"USB Audio ({card_name})",
                        "type": "usb",
                        "alsa_device": alsa_device
                    })

    return outputs


def get_available_audio_output_ids():
    """Return the IDs of currently available audio outputs."""
    return [
        output["id"]
        for output in get_audio_outputs()
    ]


def get_effective_audio_output():
    """
    Return the saved audio output if currently available.

    Falls back to System Default if unavailable.
    """
    selected = get_audio_output()
    available = get_audio_outputs()

    for output in available:
        if output["id"] == selected:
            return output

    for output in available:
        if output["id"] == DEFAULT_AUDIO_OUTPUT:
            return output

    return {
        "id": DEFAULT_AUDIO_OUTPUT,
        "name": "System Default",
        "type": "default",
        "alsa_device": "default"
    }


def get_audio_device():
    """Return the ALSA device name for the effective audio output."""
    return get_effective_audio_output()["alsa_device"]