import json
import re
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from shared.vlc_helper import log

REPO = "jdesign21/LivingPortraitApp"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases"

def parse_version(version):
    """
    Convert versions such as:
        2.0.0
        v2.0.0
        2.0.0-beta.1
        v2.0.0-beta.3
    into a tuple that can be compared.
    """
    version = version.strip().lstrip("v")
    match = re.match(
        r"^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z]+)\.?(\d+)?)?$",
        version
    )
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3))
    prerelease = match.group(4)
    prerelease_number = match.group(5)
    if prerelease is None:
        return major, minor, patch, 1, 0
    prerelease_number = int(prerelease_number) if prerelease_number else 0
    return major, minor, patch, 0, prerelease_number

def is_newer_version(installed, latest):
    installed_version = parse_version(installed)
    latest_version = parse_version(latest)
    if installed_version is None or latest_version is None:
        log(
            f"Unable to compare versions: {installed} and {latest}",
            "ERROR"
        )
        return False
    return latest_version > installed_version

def get_latest_release(channel="stable"):
    """
    Get the newest GitHub release for the selected channel.
    stable = normal releases
    beta = prereleases
    """
    if channel not in ("stable", "beta"):
        log(f"Invalid release channel: {channel}", "ERROR")
        raise ValueError("Invalid release channel.")
    log(f"Checking GitHub releases for {channel} channel.", "UPDATE")
    request = Request(
        GITHUB_RELEASES_URL,
        headers={"User-Agent": "LivingPortraitApp"}
    )
    try:
        with urlopen(request, timeout=10) as response:
            releases = json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        log(f"GitHub returned HTTP {e.code}.", "ERROR")
        raise RuntimeError(f"GitHub returned HTTP {e.code}")
    except URLError as e:
        log(f"Unable to connect to GitHub: {e.reason}", "ERROR")
        raise RuntimeError(f"Unable to connect to GitHub: {e.reason}")
    except Exception as e:
        log(f"Failed to check GitHub releases: {e}", "ERROR")
        raise RuntimeError(f"Failed to check GitHub releases: {e}")
    valid_releases = []
    for release in releases:
        if release.get("draft", False):
            continue
        if channel == "beta":
            if not release.get("prerelease", False):
                continue
        elif release.get("prerelease", False):
            continue
        tag_name = release.get("tag_name", "").strip()
        if not tag_name or parse_version(tag_name) is None:
            continue
        valid_releases.append(release)
    if not valid_releases:
        log(f"No {channel} releases were found.", "ERROR")
        raise RuntimeError(f"No {channel} releases were found.")
    valid_releases.sort(
        key=lambda release: parse_version(release["tag_name"]),
        reverse=True
    )
    latest = valid_releases[0]
    log(
        f"Latest {channel} release found: {latest['tag_name']}",
        "UPDATE"
    )
    return {
        "version": latest["tag_name"].lstrip("v"),
        "tag_name": latest["tag_name"],
        "name": latest.get("name", ""),
        "url": latest.get("html_url", ""),
        "published_at": latest.get("published_at", "")
    }

def check_for_update(installed_version, channel="stable"):
    """
    Compare the installed version with the latest
    GitHub release for the selected channel.
    """
    latest = get_latest_release(channel)
    update_available = is_newer_version(
        installed_version,
        latest["version"]
    )
    log(
        f"Update check complete. Installed: {installed_version}, "
        f"Latest: {latest['version']}, "
        f"Update available: {update_available}",
        "UPDATE"
    )
    return {
        "installed_version": installed_version,
        "latest_version": latest["version"],
        "tag_name": latest["tag_name"],
        "update_available": update_available,
        "release_name": latest["name"],
        "release_url": latest["url"],
        "published_at": latest["published_at"],
        "channel": channel
    }