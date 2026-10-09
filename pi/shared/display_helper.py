
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

DRM_PATH = Path("/sys/class/drm")
FRAMEBUFFER_SIZE = Path("/sys/class/graphics/fb0/virtual_size")
CMDLINE_PATH = Path("/boot/firmware/cmdline.txt")
DISPLAY_OVERRIDE_STATE = Path.home() / ".livingportrait_display_override.json"

_ROOT_WRITE_SCRIPT = r'''
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
data = json.load(sys.stdin)
tokens = data.get("tokens")

if not isinstance(tokens, list) or not tokens or not all(
    isinstance(token, str) and token and "\n" not in token and "\r" not in token
    for token in tokens
):
    raise ValueError("Invalid kernel command line tokens.")

original_stat = path.stat()
fd, temp_name = tempfile.mkstemp(
    prefix=f".{path.name}.",
    dir=str(path.parent),
    text=True,
)

try:
    os.fchmod(fd, stat.S_IMODE(original_stat.st_mode))
    os.fchown(fd, original_stat.st_uid, original_stat.st_gid)

    with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
        temp_file.write(" ".join(tokens) + "\n")
        temp_file.flush()
        os.fsync(temp_file.fileno())

    os.replace(temp_name, path)

    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except Exception:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(temp_name)
    except OSError:
        pass
    raise
'''


def _parse_resolution(value):
    match = re.fullmatch(r"\s*(\d+)\s*[xX,]\s*(\d+)\s*", value)
    if not match:
        return None

    width, height = int(match.group(1)), int(match.group(2))
    return {"width": width, "height": height, "label": f"{width} x {height}"}


def _run_kmsprint(*args):
    try:
        result = subprocess.run(
            ["kmsprint", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _parse_mode_line(line):
    match = re.search(r"\b(\d+)x(\d+)(i?)@([\d.]+)", line)
    if not match:
        return None

    width = int(match.group(1))
    height = int(match.group(2))
    interlaced = bool(match.group(3))
    refresh_rate = float(match.group(4))

    mode = {
        "width": width,
        "height": height,
        "refresh_rate": refresh_rate,
        "interlaced": interlaced,
        "scan_type": "interlaced" if interlaced else "progressive",
        "label": f"{width} x {height}{'i' if interlaced else ''} @ {refresh_rate:g} Hz",
    }

    if re.search(r"\b16:9\b", line):
        mode["aspect_ratio"] = "16:9"
    elif re.search(r"\b4:3\b", line):
        mode["aspect_ratio"] = "4:3"

    return mode


def _get_active_mode(kms_output):
    for line in kms_output.splitlines():
        if re.search(r"\bCrtc\b", line, re.IGNORECASE):
            mode = _parse_mode_line(line)
            if mode:
                return mode
    return None


def _get_framebuffer_resolution():
    try:
        return _parse_resolution(FRAMEBUFFER_SIZE.read_text().strip())
    except (OSError, ValueError):
        return None


def _get_drm_connectors():
    connectors = []
    available_modes = set()

    if not DRM_PATH.exists():
        return connectors, available_modes

    for connector_path in sorted(DRM_PATH.glob("card*-HDMI-*")):
        try:
            status = (connector_path / "status").read_text().strip()
        except OSError:
            continue

        if status != "connected":
            continue

        connector = {
            "name": connector_path.name.split("-", 1)[1],
            "status": status,
            "modes": [],
        }

        try:
            mode_lines = (connector_path / "modes").read_text().splitlines()
        except OSError:
            mode_lines = []

        for mode_line in mode_lines:
            resolution = _parse_resolution(mode_line)
            if not resolution:
                continue

            key = (resolution["width"], resolution["height"])
            if key not in available_modes:
                available_modes.add(key)
                connector["modes"].append(resolution)

        connectors.append(connector)

    return connectors, available_modes


def _mode_key(mode):
    return (
        mode["width"],
        mode["height"],
        round(mode["refresh_rate"], 3)
        if mode.get("refresh_rate") is not None
        else None,
        mode.get("interlaced", False),
    )


def _get_available_modes(kms_modes_output):
    modes_by_key = {}

    for line in kms_modes_output.splitlines():
        mode = _parse_mode_line(line)
        if not mode:
            continue

        # Hide interlaced modes from the selection list.
        if mode.get("interlaced", False):
            continue

        refresh_rate = mode.get("refresh_rate")
        if refresh_rate is None:
            continue

        # Keep only refresh rates effectively equal to a whole number.
        # For example, 60.00 is kept; 59.94 and 60.32 are excluded.
        standard_rate = round(refresh_rate)
        if abs(refresh_rate - standard_rate) >= 0.01:
            continue

        # Use the whole-number rate consistently in the UI and boot setting.
        mode["refresh_rate"] = float(standard_rate)
        mode["scan_type"] = "progressive"
        mode["label"] = (
            f"{mode['width']} x {mode['height']} @ {standard_rate} Hz"
        )

        key = _mode_key(mode)
        existing = modes_by_key.get(key)

        if existing is None:
            modes_by_key[key] = mode
        elif not existing.get("aspect_ratio") and mode.get("aspect_ratio"):
            modes_by_key[key] = mode

    return list(modes_by_key.values())


def _get_fallback_modes(available_resolution_keys):
    return [
        {
            "width": width,
            "height": height,
            "refresh_rate": None,
            "interlaced": False,
            "scan_type": "progressive",
            "aspect_ratio": None,
            "label": f"{width} x {height}",
        }
        for width, height in sorted(available_resolution_keys)
    ]


def get_display_info():
    kms_output = _run_kmsprint()
    kms_modes_output = _run_kmsprint("-m")

    detected_mode = _get_active_mode(kms_output)
    connectors, available_resolution_keys = _get_drm_connectors()
    available_modes = _get_available_modes(kms_modes_output)

    current_mode = detected_mode
    if current_mode is None:
        current_mode = _get_framebuffer_resolution()

    if not available_modes:
        available_modes = _get_fallback_modes(available_resolution_keys)

    return {
        "current_resolution": current_mode,
        "available_modes": available_modes,
        "available_resolutions": [
            {
                "width": width,
                "height": height,
                "label": f"{width} x {height}",
            }
            for width, height in sorted(available_resolution_keys)
        ],
        "connectors": connectors,
        "detection_method": (
            "kmsprint" if detected_mode else
            "framebuffer" if current_mode else
            "unavailable"
        ),
    }


def _read_cmdline(path=CMDLINE_PATH):
    """Read the single kernel command line without modifying its parameters."""
    content = Path(path).read_text(encoding="utf-8").strip()

    if not content or "\n" in content or "\r" in content:
        raise ValueError("cmdline.txt must contain one non-empty line.")

    return content.split()


def _write_cmdline(tokens, path=CMDLINE_PATH):
    """Atomically write cmdline.txt, using sudo when root ownership requires it."""
    path = Path(path)

    if not tokens:
        raise ValueError("Refusing to write an empty kernel command line.")

    if not all(
        isinstance(token, str) and token and "\n" not in token and "\r" not in token
        for token in tokens
    ):
        raise ValueError("Invalid kernel command line tokens.")

    original_stat = path.stat()
    current_uid = os.geteuid()

    # Use existing passwordless sudo permission when root owns the boot file.
    if current_uid != 0 and original_stat.st_uid != current_uid:
        result = subprocess.run(
            [
                "sudo",
                "-n",
                "/usr/bin/python3",
                "-c",
                _ROOT_WRITE_SCRIPT,
                str(path),
            ],
            input=json.dumps({"tokens": tokens}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise PermissionError(
                "Unable to update the boot command line through sudo"
                + (f": {detail}" if detail else ".")
            )
        return

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )

    try:
        os.fchmod(fd, stat.S_IMODE(original_stat.st_mode))
        if current_uid == 0:
            os.fchown(fd, original_stat.st_uid, original_stat.st_gid)

        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(" ".join(tokens) + "\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_name, path)

        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _write_state(state, path=DISPLAY_OVERRIDE_STATE):
    """Atomically save the state needed to restore the previous override."""
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as state_file:
            os.fchmod(state_file.fileno(), 0o600)
            json.dump(state, state_file, indent=2)
            state_file.write("\n")
            state_file.flush()
            os.fsync(state_file.fileno())

        os.replace(temp_name, path)

    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _get_connected_hdmi_connector():
    connectors = get_display_info().get("connectors", [])

    if not connectors:
        raise RuntimeError("No connected HDMI display was detected.")

    return connectors[0]["name"]


def _get_saved_override_state(path=DISPLAY_OVERRIDE_STATE):
    path = Path(path)
    if not path.exists():
        return None

    state = json.loads(path.read_text(encoding="utf-8"))
    connector = state.get("connector")
    managed_override = state.get("managed_override")
    previous_override = state.get("previous_override")

    if (
        not isinstance(connector, str)
        or not re.fullmatch(r"HDMI-A-\d+", connector)
        or not isinstance(managed_override, str)
        or not managed_override.startswith(f"video={connector}:")
        or (
            previous_override is not None
            and (
                not isinstance(previous_override, str)
                or not previous_override.startswith(f"video={connector}:")
            )
        )
    ):
        raise ValueError("Saved display override state is invalid.")

    return state


def apply_display_mode(mode, cmdline_path=CMDLINE_PATH):
    """Configure the selected HDMI mode for the next boot. Does not reboot."""
    if not isinstance(mode, dict):
        raise ValueError("Display mode must be a dictionary.")

    width = mode.get("width")
    height = mode.get("height")
    refresh_rate = mode.get("refresh_rate")
    interlaced = mode.get("interlaced", False)

    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
        or width <= 0
        or height <= 0
    ):
        raise ValueError("Invalid display dimensions.")

    if not isinstance(interlaced, bool):
        raise ValueError("Invalid display scan type.")

    if interlaced:
        raise ValueError("Interlaced display modes are not supported.")

    if (
        not isinstance(refresh_rate, (int, float))
        or isinstance(refresh_rate, bool)
        or not 1 <= refresh_rate <= 1000
        or abs(refresh_rate - round(refresh_rate)) >= 0.01
    ):
        raise ValueError("A standard whole-number refresh rate is required.")

    display_info = get_display_info()
    supported = any(
        candidate.get("width") == width
        and candidate.get("height") == height
        and not candidate.get("interlaced", False)
        and candidate.get("refresh_rate") is not None
        and abs(candidate["refresh_rate"] - refresh_rate) < 0.01
        for candidate in display_info.get("available_modes", [])
    )

    if not supported:
        raise ValueError("The requested display mode is not detected.")

    connector = _get_connected_hdmi_connector()
    if not re.fullmatch(r"HDMI-A-\d+", connector):
        raise ValueError("Unsupported HDMI connector name.")

    refresh_text = str(int(round(refresh_rate)))
    override = f"video={connector}:{width}x{height}@{refresh_text}D"

    tokens = _read_cmdline(cmdline_path)
    prefix = f"video={connector}:"
    previous = [token for token in tokens if token.startswith(prefix)]

    if len(previous) > 1:
        raise ValueError(
            f"Multiple video parameters exist for {connector}; "
            "resolve them before applying a new mode."
        )

    old_state = _get_saved_override_state()
    previous_override = previous[0] if previous else None

    if (
        old_state
        and old_state["connector"] == connector
        and previous_override == old_state["managed_override"]
    ):
        previous_override = old_state["previous_override"]

    state = {
        "connector": connector,
        "managed_override": override,
        "previous_override": previous_override,
    }

    updated_tokens = [
        token for token in tokens if not token.startswith(prefix)
    ]
    updated_tokens.append(override)

    state_path = DISPLAY_OVERRIDE_STATE
    previous_state_content = (
        state_path.read_bytes() if state_path.exists() else None
    )

    _write_state(state, state_path)

    try:
        _write_cmdline(updated_tokens, cmdline_path)
    except Exception:
        if previous_state_content is None:
            try:
                state_path.unlink()
            except OSError:
                pass
        else:
            state_path.write_bytes(previous_state_content)
        raise

    return override


def restore_default_display_mode(cmdline_path=CMDLINE_PATH):
    """Remove this application's override and restore the previous setting."""
    state = _get_saved_override_state()
    if not state:
        return (
            "No LivingPortraitApp override is saved. "
            "Automatic display detection is unchanged."
        )

    connector = state["connector"]
    managed_override = state["managed_override"]
    previous_override = state["previous_override"]
    tokens = _read_cmdline(cmdline_path)

    if managed_override not in tokens:
        raise RuntimeError(
            "The saved LivingPortraitApp override is not present in cmdline.txt. "
            "No changes were made."
        )

    updated_tokens = [
        token for token in tokens if token != managed_override
    ]

    if previous_override:
        prefix = f"video={connector}:"
        if any(token.startswith(prefix) for token in updated_tokens):
            raise RuntimeError(
                "Another override exists for this connector; no changes were made."
            )
        updated_tokens.append(previous_override)

    _write_cmdline(updated_tokens, cmdline_path)

    try:
        Path(DISPLAY_OVERRIDE_STATE).unlink()
    except Exception:
        _write_cmdline(tokens, cmdline_path)
        raise

    return (
        "Display override removed. Automatic display detection will resume "
        "after you reboot the Raspberry Pi."
    )


if __name__ == "__main__":
    print(json.dumps(get_display_info(), indent=2))
