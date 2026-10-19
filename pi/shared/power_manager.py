
"""Power management helpers for LivingPortraitApp."""

import subprocess
import threading
import time
from datetime import datetime

from shared.vlc_helper import load_settings, save_settings, log

_scheduler_thread = None
_scheduler_lock = threading.Lock()


def _run_shutdown():
    """Request a clean operating-system shutdown and check for errors."""
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode == 0:
            log("Scheduled shutdown command accepted.", "POWER")
            return True

        error_message = result.stderr.strip() or (
            f"Shutdown command exited with code {result.returncode}."
        )
        log(f"Scheduled shutdown failed: {error_message}", "ERROR")
        return False

    except subprocess.TimeoutExpired:
        log("Scheduled shutdown command timed out.", "ERROR")
        return False

    except Exception as exc:
        log(f"Unable to request scheduled shutdown: {exc}", "ERROR")
        return False


def _scheduler_loop():
    while True:
        try:
            now = datetime.now()
            settings = load_settings()
            schedule = settings.get("power_schedule", {})

            target_time = schedule.get("shutdown_time", "")
            enabled = schedule.get("shutdown_enabled", False)
            today = now.strftime("%Y-%m-%d")
            current_time = now.strftime("%H:%M")

            if (
                enabled
                and target_time == current_time
                and schedule.get("last_shutdown_date") != today
            ):
                # Request shutdown first. Only record the date if the
                # operating system accepts the command.
                if _run_shutdown():
                    settings = load_settings()
                    schedule = settings.get("power_schedule", {})

                    schedule["last_shutdown_date"] = today
                    settings["power_schedule"] = schedule
                    save_settings(settings)

        except Exception as exc:
            log(f"Power scheduler error: {exc}", "ERROR")

        time.sleep(20)


def start_power_scheduler():
    """Start one scheduler thread in the Flask process."""
    global _scheduler_thread

    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return

        _scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            name="livingportrait-power-scheduler",
            daemon=True,
        )
        _scheduler_thread.start()
