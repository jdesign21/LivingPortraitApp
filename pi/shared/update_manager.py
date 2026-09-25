import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import subprocess
from shared.vlc_helper import log

HOME = Path.home()
REPO = "jdesign21/LivingPortraitApp"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases"
UPDATE_ITEMS = [
    "flask_ui",
    "shared",
    "motion_vlc.py",
    "motion_vlc_primary.py",
    "motion_vlc_secondary.py",
    "mqtt_client.py",
    "version.txt",
]
PROTECTED_ITEMS = [
    "videos",
    "logs",
    "settings.json",
    "network_pis.json",
    "mqtt_status.json",
    "flask_venv",
    "pause_video",
    "images",
]
STATUS_FILE = HOME / "update_status.json"

def write_status(status, message, error=False):
    """
    Write the current update status and maintain
    a history of all update steps.
    """
    try:
        history = []
        if STATUS_FILE.exists():
            try:
                with open(STATUS_FILE, "r") as f:
                    previous = json.load(f)
                    history = previous.get("history", [])
            except Exception:
                history = []
        history.append({
            "status": status,
            "message": message,
            "error": error,
            "time": time.strftime("%H:%M:%S")
        })
        data = {
            "status": status,
            "message": message,
            "error": error,
            "history": history
        }
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f"Failed to write update status: {e}", "ERROR")

def get_release(tag_name):
    url = f"{GITHUB_RELEASES_URL}/tags/{tag_name}"
    request = Request(
        url,
        headers={"User-Agent": "LivingPortraitApp"}
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        log(f"GitHub returned HTTP {e.code} while retrieving release.", "ERROR")
        raise RuntimeError(f"GitHub returned HTTP {e.code}")
    except URLError as e:
        log(f"Unable to connect to GitHub: {e.reason}", "ERROR")
        raise RuntimeError(f"Unable to connect to GitHub: {e.reason}")
    except Exception as e:
        log(f"Failed to retrieve GitHub release: {e}", "ERROR")
        raise RuntimeError(f"Failed to retrieve GitHub release: {e}")

def download_release(tag_name, destination):
    release = get_release(tag_name)
    zip_url = release.get("zipball_url")
    if not zip_url:
        log("GitHub release does not contain a download archive.", "ERROR")
        raise RuntimeError("GitHub release does not contain a download archive.")
    zip_path = destination / "release.zip"
    request = Request(
        zip_url,
        headers={"User-Agent": "LivingPortraitApp"}
    )
    try:
        with urlopen(request, timeout=60) as response:
            with open(zip_path, "wb") as f:
                shutil.copyfileobj(response, f)
    except HTTPError as e:
        log(f"GitHub returned HTTP {e.code} while downloading.", "ERROR")
        raise RuntimeError(f"GitHub returned HTTP {e.code} while downloading.")
    except URLError as e:
        log(f"Unable to download release: {e.reason}", "ERROR")
        raise RuntimeError(f"Unable to download release: {e.reason}")
    log(f"Release {tag_name} downloaded successfully.", "UPDATE")
    return zip_path

def find_pi_folder(extract_path):
    matches = list(extract_path.glob("*/pi"))
    if not matches:
        log("The GitHub release does not contain a pi folder.", "ERROR")
        raise RuntimeError("The GitHub release does not contain a pi folder.")
    if len(matches) > 1:
        log("Multiple pi folders were found in the release.", "ERROR")
        raise RuntimeError("Multiple pi folders were found in the release.")
    return matches[0]

def backup_application(backup_path):
    backup_path.mkdir(parents=True, exist_ok=True)
    for item in UPDATE_ITEMS:
        source = HOME / item
        if not source.exists():
            continue
        destination = backup_path / item
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    log("Current application files backed up successfully.", "UPDATE")

def remove_existing_item(path):
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()

def install_application(pi_folder):
    for item in UPDATE_ITEMS:
        source = pi_folder / item
        if not source.exists():
            continue
        destination = HOME / item
        remove_existing_item(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    log("Application files installed successfully.", "UPDATE")

def restart_services(backup_path):
    write_status("restarting", "Restarting LivingPortraitApp...")
    log("Restarting LivingPortraitApp services.", "UPDATE")
    time.sleep(2)
    # Restart VLC first. Flask must be restarted last because
    # the updater is running from the Flask service.
    subprocess.run(
        ["sudo", "systemctl", "restart", "motion_vlc"],
        check=True
    )
    log("motion_vlc service restarted successfully.", "UPDATE")
    # The update has successfully installed and motion_vlc restarted.
    # The backup is no longer needed.
    if backup_path and backup_path.exists():
        shutil.rmtree(backup_path, ignore_errors=True)
        log("Update backup removed.", "UPDATE")
    write_status(
        "complete",
        "LivingPortraitApp update completed successfully."
    )
    log("LivingPortraitApp update completed successfully.", "UPDATE")
    time.sleep(1)
    # Restart Flask last.
    subprocess.run(
        ["sudo", "systemctl", "restart", "flask_ui"],
        check=True
    )
    log("flask_ui service restarted successfully.", "UPDATE")

def perform_update(tag_name):
    backup_path = None
    try:
        write_status("starting", f"Preparing update to {tag_name}...")
        log(f"Preparing update to {tag_name}.", "UPDATE")
        with tempfile.TemporaryDirectory(
            prefix="livingportrait_update_"
        ) as temp_dir:
            temp_path = Path(temp_dir)
            extract_path = temp_path / "extracted"
            extract_path.mkdir()
            write_status(
                "downloading",
                f"Downloading {tag_name} from GitHub..."
            )
            log(f"Downloading release {tag_name}.", "UPDATE")
            zip_path = download_release(tag_name, temp_path)
            write_status(
                "extracting",
                "Extracting application files..."
            )
            log("Extracting application files.", "UPDATE")
            with zipfile.ZipFile(zip_path, "r") as archive:
                archive.extractall(extract_path)
            pi_folder = find_pi_folder(extract_path)
            required_files = [
                "motion_vlc.py",
                "motion_vlc_primary.py",
                "motion_vlc_secondary.py",
                "mqtt_client.py",
                "version.txt",
                "shared",
                "flask_ui",
            ]
            missing = [
                item
                for item in required_files
                if not (pi_folder / item).exists()
            ]
            if missing:
                message = (
                    "Release is missing required files: "
                    + ", ".join(missing)
                )
                log(message, "ERROR")
                raise RuntimeError(message)
            write_status(
                "backing_up",
                "Backing up current application..."
            )
            backup_path = HOME / f".livingportrait_backup_{int(time.time())}"
            backup_application(backup_path)
            write_status(
                "installing",
                "Installing application update..."
            )
            install_application(pi_folder)
            write_status(
                "installed",
                f"Update to {tag_name} installed."
            )
            log(f"Update to {tag_name} installed.", "UPDATE")
            restart_services(backup_path)
    except Exception as e:
        log(f"Update to {tag_name} failed: {e}", "ERROR")
        write_status("failed", f"Update failed: {e}", error=True)
        if backup_path and backup_path.exists():
            try:
                log("Restoring application from backup.", "UPDATE")
                for item in UPDATE_ITEMS:
                    backup_item = backup_path / item
                    if not backup_item.exists():
                        continue
                    destination = HOME / item
                    remove_existing_item(destination)
                    if backup_item.is_dir():
                        shutil.copytree(backup_item, destination)
                    else:
                        shutil.copy2(backup_item, destination)
                try:
                    subprocess.run(
                        ["sudo", "systemctl", "restart", "flask_ui"],
                        check=False
                    )
                    subprocess.run(
                        ["sudo", "systemctl", "restart", "motion_vlc"],
                        check=False
                    )
                    log(
                        "Application restored and services restarted.",
                        "UPDATE"
                    )
                except Exception as restore_service_error:
                    log(
                        f"Failed to restart services after restoration: "
                        f"{restore_service_error}",
                        "ERROR"
                    )
            except Exception as restore_error:
                log(
                    f"Failed to restore application backup: {restore_error}",
                    "ERROR"
                )

def start_update(tag_name):
    if not tag_name:
        raise ValueError("Release tag is required.")
    if "/" in tag_name or "\\" in tag_name:
        raise ValueError("Invalid release tag.")
    try:
        if STATUS_FILE.exists():
            STATUS_FILE.unlink()
    except Exception as e:
        log(f"Failed to clear previous update status: {e}", "ERROR")
    write_status("starting", f"Starting update to {tag_name}...")
    log(f"Starting update to {tag_name}.", "UPDATE")
    subprocess.Popen(
        [
            "python3",
            "-c",
            (
                "from shared.update_manager import "
                "perform_update; "
                f"perform_update({tag_name!r})"
            )
        ],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )