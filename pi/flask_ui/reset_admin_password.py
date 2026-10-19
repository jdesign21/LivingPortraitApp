#!/usr/bin/env python3
"""Reset the LivingPortraitApp administrator password from the local Pi account."""
import getpass
import sys
from pathlib import Path

HOME = Path.home()
sys.path.insert(0, str(HOME))

from shared.auth_manager import reset_admin_password, validate_password


def main():
    print("LivingPortraitApp administrator password recovery")
    print("Run this script locally on the Raspberry Pi as the account that runs LivingPortraitApp.")
    password = getpass.getpass("New password (minimum 12 characters): ")
    if not validate_password(password):
        print("Password must be at least 12 characters and have no leading/trailing whitespace.")
        return 1
    confirm = getpass.getpass("Confirm new password: ")
    if password != confirm:
        print("Passwords do not match.")
        return 1
    try:
        reset_admin_password(password)
    except Exception as exc:
        print(f"Unable to reset administrator password: {exc}")
        return 1
    print("Administrator password reset. Existing web sessions will be invalidated.")
    print("Restart the Flask service with: sudo systemctl restart flask_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
