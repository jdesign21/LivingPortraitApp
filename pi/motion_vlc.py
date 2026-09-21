#!/usr/bin/env python3

import sys
import traceback

from shared.vlc_network_helper import get_role


def main():
    role = get_role()

    print(f"Starting VLC in {role} mode...")

    if role == "primary":
        from motion_vlc_primary import main as primary_main
        primary_main()

    elif role == "secondary":
        from motion_vlc_secondary import main as secondary_main
        secondary_main()

    else:
        raise ValueError(
            f"Invalid role '{role}'. "
            "Role must be 'primary' or 'secondary'."
        )


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("Exiting.")

    except Exception:
        print("motion_vlc.py crashed:")
        traceback.print_exc()
        sys.exit(1)

