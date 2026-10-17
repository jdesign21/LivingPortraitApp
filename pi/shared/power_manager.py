"""Power management helpers for LivingPortraitApp."""

import subprocess
import threading
import time
from datetime import datetime

from shared.vlc_helper import load_settings, save_settings, log

_scheduler_thread = None
_scheduler_lock = threading.Lock()


def _run_shutdown():
    """Request a clean operating-system shutdown using the restricted sudo rule."""
    try:
        subprocess.Popen(
            ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log("Scheduled shutdown requested.", "POWER")
    except Exception as exc:
        log(f"Unable to request scheduled shutdown: {exc}", "ERROR")


def _scheduler_loop():
    while True:
        try:
            now = datetime.now()
            settings = load_settings()
            schedule = settings.get("power_schedule", {})
            target_time = schedule.get("shutdown_time", "")
            enabled = schedule.get("shutdown_enabled", False)
            today = now.strftime("%Y-%m-%d")

            if (
                enabled
                and target_time == now.strftime("%H:%M")
                and schedule.get("last_shutdown_date") != today
            ):
                # Persist the run date before requesting shutdown to prevent
                # repeated requests if the command takes time to stop the Pi.
                schedule["last_shutdown_date"] = today
                settings["power_schedule"] = schedule
                save_settings(settings)
                _run_shutdown()
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