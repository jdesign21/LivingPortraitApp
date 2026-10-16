#!/usr/bin/python3
"""Restricted root helper for changing only one HDMI video= override."""

import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

CMDLINE_PATH = Path("/boot/firmware/cmdline.txt")
VIDEO_RE = re.compile(r"^video=(HDMI-A-\d+):(\d+)x(\d+)@(\d+)D$")
CONNECTOR_RE = re.compile(r"^video=(HDMI-A-\d+):")


def main():
    if len(sys.argv) != 1:
        raise ValueError("This helper accepts JSON on stdin and no arguments.")

    proposed = json.load(sys.stdin).get("tokens")
    if not isinstance(proposed, list) or not proposed or not all(
        isinstance(token, str) and token and "\n" not in token and "\r" not in token
        for token in proposed
    ):
        raise ValueError("Invalid kernel command line tokens.")

    path = CMDLINE_PATH
    original_stat = path.stat()
    current_content = path.read_text(encoding="utf-8").strip()
    if not current_content or "\n" in current_content or "\r" in current_content:
        raise ValueError("cmdline.txt must contain one non-empty line.")
    current = current_content.split()

    def connector_for(token):
        match = CONNECTOR_RE.fullmatch(token.split(":", 1)[0] + ":") if token.startswith("video=HDMI-A-") else None
        return match.group(1) if match else None

    connectors = {
        connector
        for token in current + proposed
        if (connector := connector_for(token)) is not None
    }

    changed_connectors = []
    for connector in connectors:
        prefix = f"video={connector}:"
        old = [token for token in current if token.startswith(prefix)]
        new = [token for token in proposed if token.startswith(prefix)]
        if old != new:
            changed_connectors.append(connector)

    if len(changed_connectors) != 1:
        raise ValueError("Only one HDMI video override may be changed at a time.")

    connector = changed_connectors[0]
    prefix = f"video={connector}:"
    current_target = [token for token in current if token.startswith(prefix)]
    proposed_target = [token for token in proposed if token.startswith(prefix)]

    if len(current_target) > 1 or len(proposed_target) > 1:
        raise ValueError("Multiple overrides exist for the selected HDMI connector.")

    if proposed_target:
        match = VIDEO_RE.fullmatch(proposed_target[0])
        if not match:
            raise ValueError("The HDMI video override format is invalid.")
        width, height, refresh = map(int, match.groups()[1:])
        if not (320 <= width <= 16384 and 200 <= height <= 8640 and 1 <= refresh <= 1000):
            raise ValueError("The HDMI video override dimensions are out of range.")
    elif len(current_target) != 1:
        raise ValueError("A single existing HDMI override is required to remove it.")

    current_other = [token for token in current if not token.startswith(prefix)]
    proposed_other = [token for token in proposed if not token.startswith(prefix)]
    if current_other != proposed_other:
        raise ValueError("This helper may only change the selected HDMI video override.")

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
    try:
        os.fchmod(fd, stat.S_IMODE(original_stat.st_mode))
        os.fchown(fd, original_stat.st_uid, original_stat.st_gid)
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(" ".join(proposed) + "\n")
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


if __name__ == "__main__":
    main()
