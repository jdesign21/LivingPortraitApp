
import platform
import os
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path


def _run_command(command, timeout=5):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )

        return result.stdout.strip()

    except Exception:
        return ""


def _get_ip_address():
    output = _run_command(["hostname", "-I"], 3)

    if output:
        return output.split()[0]

    return "Unavailable"


def _get_pi_model():
    try:
        model_file = Path("/proc/device-tree/model")

        if model_file.exists():
            model = model_file.read_text(
                encoding="utf-8",
                errors="replace"
            ).replace("\x00", "").strip()

            if model:
                return model

    except Exception:
        pass

    return "Unavailable"


def _get_os_version():
    try:
        os_release = {}

        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                if "=" not in line:
                    continue

                key, value = line.strip().split("=", 1)
                os_release[key] = value.strip('"')

        return os_release.get(
            "PRETTY_NAME",
            "Unavailable"
        )

    except Exception:
        return "Unavailable"


def _get_vlc_version():
    output = _run_command(["vlc", "--version"], 5)

    if output:
        first_line = output.splitlines()[0].strip()

        if first_line.lower().startswith("vlc"):
            return first_line

    return "Unavailable"


def _get_hardware_serial():
    try:
        serial_file = Path(
            "/sys/firmware/devicetree/base/serial-number"
        )

        if serial_file.exists():
            serial = serial_file.read_text(
                encoding="utf-8",
                errors="replace"
            ).replace("\x00", "").strip()

            if serial:
                return serial

    except Exception:
        pass

    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("serial"):
                    parts = line.split(":", 1)

                    if len(parts) == 2:
                        serial = parts[1].strip()

                        if serial:
                            return serial

    except Exception:
        pass

    return "Unavailable"


def _get_cpu_temperature():
    try:
        temp_file = Path(
            "/sys/class/thermal/thermal_zone0/temp"
        )

        if temp_file.exists():
            temperature = int(
                temp_file.read_text().strip()
            ) / 1000

            return f"{temperature:.1f}°C"

    except Exception:
        pass

    return "Unavailable"


def _read_cpu_times():
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("cpu "):
                    continue

                parts = line.split()

                if len(parts) < 5:
                    return None

                values = [
                    int(value)
                    for value in parts[1:]
                ]

                idle = values[3]

                if len(values) > 4:
                    idle += values[4]

                total = sum(values)

                return total, idle

    except Exception:
        pass

    return None


def _get_cpu_usage():
    try:
        first = _read_cpu_times()

        if not first:
            return "Unavailable"

        time.sleep(0.1)

        second = _read_cpu_times()

        if not second:
            return "Unavailable"

        total_delta = second[0] - first[0]
        idle_delta = second[1] - first[1]

        if total_delta <= 0:
            return "Unavailable"

        usage = (
            (total_delta - idle_delta)
            / total_delta
        ) * 100

        usage = max(0, min(100, usage))

        return f"{usage:.1f}%"

    except Exception:
        return "Unavailable"


def _get_memory_usage():
    try:
        output = _run_command(["free", "-m"], 3)

        for line in output.splitlines():
            if not line.startswith("Mem:"):
                continue

            parts = line.split()

            if len(parts) >= 3:
                total = float(parts[1])
                used = float(parts[2])

                if total > 0:
                    percent = (used / total) * 100
                    return f"{percent:.1f}%"

    except Exception:
        pass

    return "Unavailable"


def _get_load_average():
    try:
        load_average = os.getloadavg()

        return {
            "one": f"{load_average[0]:.2f}",
            "five": f"{load_average[1]:.2f}",
            "fifteen": f"{load_average[2]:.2f}"
        }

    except Exception:
        try:
            values = Path(
                "/proc/loadavg"
            ).read_text().split()

            if len(values) >= 3:
                return {
                    "one": values[0],
                    "five": values[1],
                    "fifteen": values[2]
                }

        except Exception:
            pass

    return {
        "one": "Unavailable",
        "five": "Unavailable",
        "fifteen": "Unavailable"
    }


def _get_uptime():
    try:
        uptime_seconds = float(
            Path("/proc/uptime").read_text().split()[0]
        )

        days = int(uptime_seconds // 86400)
        hours = int(
            (uptime_seconds % 86400) // 3600
        )
        minutes = int(
            (uptime_seconds % 3600) // 60
        )

        parts = []

        if days:
            parts.append(
                f"{days} day{'s' if days != 1 else ''}"
            )

        if hours:
            parts.append(
                f"{hours} hour{'s' if hours != 1 else ''}"
            )

        parts.append(
            f"{minutes} minute{'s' if minutes != 1 else ''}"
        )

        return ", ".join(parts)

    except Exception:
        return "Unavailable"


def _get_boot_time():
    try:
        uptime_seconds = float(
            Path("/proc/uptime").read_text().split()[0]
        )

        boot_timestamp = time.time() - uptime_seconds

        return datetime.fromtimestamp(
            boot_timestamp
        ).strftime("%Y-%m-%d %I:%M:%S %p")

    except Exception:
        return "Unavailable"


def _get_disk_info():
    info = {
        "device": "Unavailable",
        "used_percent": 0,
        "free_percent": 0,
        "free_gib": 0,
        "total_gib": 0
    }

    try:
        output = _run_command(
            ["df", "-B1", "/"],
            5
        )

        lines = output.splitlines()

        if len(lines) < 2:
            return info

        parts = lines[-1].split()

        if len(parts) < 5:
            return info

        device = parts[0]
        total_bytes = int(parts[1])
        used_bytes = int(parts[2])
        free_bytes = int(parts[3])

        if total_bytes <= 0:
            return info

        used_percent = round(
            (used_bytes / total_bytes) * 100
        )

        info["device"] = device.replace(
            "/dev/",
            ""
        )
        info["used_percent"] = used_percent
        info["free_percent"] = 100 - used_percent
        info["free_gib"] = round(
            free_bytes / (1024 ** 3),
            2
        )
        info["total_gib"] = round(
            total_bytes / (1024 ** 3),
            2
        )

    except Exception:
        pass

    return info


def _is_command_available(command):
    try:
        result = subprocess.run(
            ["sh", "-c", f"command -v {command}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False
        )

        return result.returncode == 0

    except Exception:
        return False


def get_system_info():
    """Return Raspberry Pi and system information for the About page."""
    disk = _get_disk_info()
    load_average = _get_load_average()

    return {
        "hostname": socket.gethostname(),
        "ip_address": _get_ip_address(),
        "pi_model": _get_pi_model(),
        "os_version": _get_os_version(),
        "kernel_version": platform.release(),
        "architecture": platform.machine(),
        "vlc_version": _get_vlc_version(),
        "hardware_serial": _get_hardware_serial(),
        "audio_system": "ALSA",
        "pulseaudio": _is_command_available("pulseaudio"),
        "pipewire": _is_command_available("pipewire"),
        "cpu_temperature": _get_cpu_temperature(),
        "cpu_usage": _get_cpu_usage(),
        "memory_usage": _get_memory_usage(),
        "load_average": load_average,
        "uptime": _get_uptime(),
        "boot_time": _get_boot_time(),
        "disk_device": disk["device"],
        "disk_used_percent": disk["used_percent"],
        "disk_free_percent": disk["free_percent"],
        "disk_free_gib": disk["free_gib"],
        "disk_total_gib": disk["total_gib"]
    }

