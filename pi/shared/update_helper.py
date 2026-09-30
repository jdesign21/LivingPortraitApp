import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse, unquote
from shared.vlc_helper import log

REPO = "jdesign21/LivingPortraitApp"
GITHUB_RELEASES_FEED = f"https://github.com/{REPO}/releases.atom"

HOME = Path.home()
UPDATE_CACHE_FILE = HOME / "update_status.json"
UPDATE_CHECK_INTERVAL = 12 * 60 * 60  # 12 hours

ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"


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

    # Stable releases sort higher than prereleases
    # of the same version.
    if prerelease is None:
        return major, minor, patch, 1, 0

    prerelease_number = (
        int(prerelease_number)
        if prerelease_number
        else 0
    )

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


def load_update_cache():
    """Load the cached update information."""

    if not UPDATE_CACHE_FILE.exists():
        return {}

    try:
        with open(UPDATE_CACHE_FILE, "r") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except Exception as e:
        log(
            f"Unable to read update cache: {e}",
            "ERROR"
        )
        return {}


def save_update_cache(data):
    """Save update information locally."""

    try:
        with open(UPDATE_CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        log(
            f"Unable to save update cache: {e}",
            "ERROR"
        )


def get_cached_update(channel):
    """Return cached update information for a channel."""

    cache = load_update_cache()
    return cache.get(channel)


def update_check_needed(channel):
    """
    Return True if GitHub should be checked.

    GitHub is checked at most once every 12 hours
    for each release channel.
    """

    cached = get_cached_update(channel)

    if not cached:
        return True

    checked_at = cached.get("checked_at", 0)

    try:
        checked_at = float(checked_at)
    except (TypeError, ValueError):
        return True

    age = time.time() - checked_at

    return age >= UPDATE_CHECK_INTERVAL


def get_latest_release(channel="stable"):
    """
    Get the newest GitHub release for the selected channel.

    stable = normal releases
    beta = prereleases
    """

    if channel not in ("stable", "beta"):
        log(
            f"Invalid release channel: {channel}",
            "ERROR"
        )
        raise ValueError("Invalid release channel.")

    log(
        f"Checking GitHub releases for {channel} channel.",
        "UPDATE"
    )

    request = Request(
        GITHUB_RELEASES_FEED,
        headers={
            "User-Agent": "LivingPortraitApp"
        }
    )

    try:
        with urlopen(request, timeout=10) as response:
            feed_data = response.read()

    except HTTPError as e:
        log(
            f"GitHub returned HTTP {e.code}.",
            "ERROR"
        )
        raise RuntimeError(
            f"GitHub returned HTTP {e.code}"
        )

    except URLError as e:
        log(
            f"Unable to connect to GitHub: {e.reason}",
            "ERROR"
        )
        raise RuntimeError(
            f"Unable to connect to GitHub: {e.reason}"
        )

    except Exception as e:
        log(
            f"Failed to check GitHub releases: {e}",
            "ERROR"
        )
        raise RuntimeError(
            f"Failed to check GitHub releases: {e}"
        )

    try:
        root = ET.fromstring(feed_data)

    except ET.ParseError as e:
        log(
            f"Failed to parse GitHub release feed: {e}",
            "ERROR"
        )
        raise RuntimeError(
            f"Failed to parse GitHub release feed: {e}"
        )

    valid_releases = []

    for entry in root.findall(
        f"{{{ATOM_NAMESPACE}}}entry"
    ):
        title_element = entry.find(
            f"{{{ATOM_NAMESPACE}}}title"
        )

        updated_element = entry.find(
            f"{{{ATOM_NAMESPACE}}}updated"
        )

        title = (
            title_element.text.strip()
            if title_element is not None and title_element.text
            else ""
        )

        published_at = (
            updated_element.text.strip()
            if updated_element is not None and updated_element.text
            else ""
        )

        release_url = ""

        for link in entry.findall(
            f"{{{ATOM_NAMESPACE}}}link"
        ):
            if link.get("rel") == "alternate":
                release_url = link.get("href", "").strip()
                break

        if not release_url:
            for link in entry.findall(
                f"{{{ATOM_NAMESPACE}}}link"
            ):
                href = link.get("href", "").strip()

                if href:
                    release_url = href
                    break

        if not release_url:
            continue

        parsed_url = urlparse(release_url)

        path_parts = [
            unquote(part)
            for part in parsed_url.path.split("/")
            if part
        ]

        if len(path_parts) < 4:
            continue

        if (
            path_parts[-2] != "tag"
            or not path_parts[-1]
        ):
            continue

        tag_name = path_parts[-1].strip()

        parsed_version = parse_version(tag_name)

        if parsed_version is None:
            continue

        is_prerelease = parsed_version[3] == 0

        if channel == "stable" and is_prerelease:
            continue

        if channel == "beta" and not is_prerelease:
            continue

        valid_releases.append({
            "version_tuple": parsed_version,
            "tag_name": tag_name,
            "name": title,
            "url": release_url,
            "published_at": published_at
        })

    if not valid_releases:
        log(
            f"No {channel} releases were found.",
            "ERROR"
        )
        raise RuntimeError(
            f"No {channel} releases were found."
        )

    valid_releases.sort(
        key=lambda release: release["version_tuple"],
        reverse=True
    )

    latest = valid_releases[0]

    log(
        f"Latest {channel} release found: "
        f"{latest['tag_name']}",
        "UPDATE"
    )

    return {
        "version": latest["tag_name"].lstrip("v"),
        "tag_name": latest["tag_name"],
        "name": latest["name"],
        "url": latest["url"],
        "published_at": latest["published_at"]
    }


def check_for_update(installed_version, channel="stable"):
    """
    Check for an update.

    GitHub is contacted only once every 12 hours.
    Between checks, the cached result is returned.
    """

    if channel not in ("stable", "beta"):
        raise ValueError("Invalid release channel.")

    # Use cached result if the 12-hour period
    # has not expired.
    if not update_check_needed(channel):
        cached = get_cached_update(channel)

        if cached:
            cached["installed_version"] = installed_version
            return cached

    # Time to contact GitHub.
    try:
        latest = get_latest_release(channel)

        update_available = is_newer_version(
            installed_version,
            latest["version"]
        )

        result = {
            "installed_version": installed_version,
            "latest_version": latest["version"],
            "tag_name": latest["tag_name"],
            "update_available": update_available,
            "release_name": latest["name"],
            "release_url": latest["url"],
            "published_at": latest["published_at"],
            "channel": channel,
            "checked_at": time.time(),
            "check_failed": False
        }

        # Save the successful check.
        cache = load_update_cache()
        cache[channel] = result
        save_update_cache(cache)

        log(
            f"Update check complete. "
            f"Installed: {installed_version}, "
            f"Latest: {latest['version']}, "
            f"Update available: {update_available}",
            "UPDATE"
        )

        return result

    except Exception as e:
        # If GitHub fails, use the previous cached result
        # instead of making the app think there is no update.
        cached = get_cached_update(channel)

        if cached:
            cached["installed_version"] = installed_version
            cached["check_failed"] = True

            log(
                f"GitHub update check failed. "
                f"Using previous cached result: {e}",
                "ERROR"
            )

            return cached

        log(
            f"GitHub update check failed and no cached result exists: {e}",
            "ERROR"
        )

        return {
            "installed_version": installed_version,
            "latest_version": None,
            "tag_name": None,
            "update_available": False,
            "release_name": None,
            "release_url": None,
            "published_at": None,
            "channel": channel,
            "checked_at": 0,
            "check_failed": True
        }