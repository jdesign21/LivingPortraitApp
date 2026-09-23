import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import subprocess

HOME = Path.home()

REPO = "jdesign21/LivingPortraitApp"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases"

# Application files/folders that may be updated.
UPDATE_ITEMS = [
    "flask_ui",
    "shared",
    "motion_vlc.py",
    "motion_vlc_primary.py",
    "motion_vlc_secondary.py",
    "mqtt_client.py",
    "version.txt",
]

# Files/folders that must never be replaced by the updater.
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
    data = {
        "status": status,
        "message": message,
        "error": error
    }

    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_release(tag_name):
    url = f"{GITHUB_RELEASES_URL}/tags/{tag_name}"

    request = Request(
        url,
        headers={
            "User-Agent": "LivingPortraitApp"
        }
    )

    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(
                response.read().decode("utf-8")
            )

    except HTTPError as e:
        raise RuntimeError(
            f"GitHub returned HTTP {e.code}"
        )

    except URLError as e:
        raise RuntimeError(
            f"Unable to connect to GitHub: {e.reason}"
        )


def download_release(tag_name, destination):
    release = get_release(tag_name)

    zip_url = release.get("zipball_url")

    if not zip_url:
        raise RuntimeError(
            "GitHub release does not contain a download archive."
        )

    zip_path = destination / "release.zip"

    request = Request(
        zip_url,
        headers={
            "User-Agent": "LivingPortraitApp"
        }
    )

    try:
        with urlopen(request, timeout=60) as response:
            with open(zip_path, "wb") as f:
                shutil.copyfileobj(response, f)

    except HTTPError as e:
        raise RuntimeError(
            f"GitHub returned HTTP {e.code} while downloading."
        )

    except URLError as e:
        raise RuntimeError(
            f"Unable to download release: {e.reason}"
        )

    return zip_path


def find_pi_folder(extract_path):
    """
    GitHub ZIP archives normally contain:

        repository-name-commit/
            pi/
                ...

    Find the pi folder without assuming the generated
    GitHub directory name.
    """

    matches = list(extract_path.glob("*/pi"))

    if not matches:
        raise RuntimeError(
            "The GitHub release does not contain a pi folder."
        )

    if len(matches) > 1:
        raise RuntimeError(
            "Multiple pi folders were found in the release."
        )

    return matches[0]


def backup_application(backup_path):
    backup_path.mkdir(parents=True, exist_ok=True)

    for item in UPDATE_ITEMS:
        source = HOME / item

        if not source.exists():
            continue

        destination = backup_path / item
        destination.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if source.is_dir():
            shutil.copytree(
                source,
                destination
            )
        else:
            shutil.copy2(
                source,
                destination
            )


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

        destination.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if source.is_dir():
            shutil.copytree(
                source,
                destination
            )
        else:
            shutil.copy2(
                source,
                destination
            )


def restart_services():
    write_status(
        "restarting",
        "Restarting LivingPortraitApp..."
    )

    time.sleep(2)

    subprocess.run(
        ["sudo", "systemctl", "restart", "flask_ui"],
        check=True
    )

    subprocess.run(
        ["sudo", "systemctl", "restart", "motion_vlc"],
        check=True
    )


def perform_update(tag_name):
    backup_path = None

    try:
        write_status(
            "starting",
            f"Preparing update to {tag_name}..."
        )

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

            zip_path = download_release(
                tag_name,
                temp_path
            )

            write_status(
                "extracting",
                "Extracting application files..."
            )

            with zipfile.ZipFile(
                zip_path,
                "r"
            ) as archive:

                archive.extractall(
                    extract_path
                )

            pi_folder = find_pi_folder(
                extract_path
            )

            # Make sure the release contains the expected
            # application files before touching the current app.
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
                raise RuntimeError(
                    "Release is missing required files: "
                    + ", ".join(missing)
                )

            write_status(
                "backing_up",
                "Backing up current application..."
            )

            backup_path = (
                HOME /
                f".livingportrait_backup_{int(time.time())}"
            )

            backup_application(
                backup_path
            )

            write_status(
                "installing",
                "Installing application update..."
            )

            install_application(
                pi_folder
            )

            write_status(
                "installed",
                f"Update to {tag_name} installed."
            )

            restart_services()

            write_status(
                "complete",
                f"LivingPortraitApp updated to {tag_name}."
            )

    except Exception as e:

        write_status(
            "failed",
            f"Update failed: {e}",
            error=True
        )

        # Restore application files if installation started
        # and something failed afterward.
        if backup_path and backup_path.exists():
            try:
                for item in UPDATE_ITEMS:
                    backup_item = backup_path / item

                    if not backup_item.exists():
                        continue

                    destination = HOME / item

                    remove_existing_item(
                        destination
                    )

                    if backup_item.is_dir():
                        shutil.copytree(
                            backup_item,
                            destination
                        )
                    else:
                        shutil.copy2(
                            backup_item,
                            destination
                        )

                try:
                    subprocess.run(
                        ["sudo", "systemctl", "restart", "flask_ui"],
                        check=False
                    )

                    subprocess.run(
                        ["sudo", "systemctl", "restart", "motion_vlc"],
                        check=False
                    )

                except Exception:
                    pass

            except Exception:
                pass


def start_update(tag_name):
    """
    Start the update in a separate process so Flask can
    continue responding while its own files are replaced.
    """

    if not tag_name:
        raise ValueError(
            "Release tag is required."
        )

    if "/" in tag_name or "\\" in tag_name:
        raise ValueError(
            "Invalid release tag."
        )

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

