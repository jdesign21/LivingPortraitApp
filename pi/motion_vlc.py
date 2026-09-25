#!/usr/bin/env python3

import sys
import traceback
from shared.vlc_network_helper import get_role
from shared.vlc_helper import log

def main():
    role = get_role()
    log(f"Starting VLC in {role} mode.", "SYSTEM")
    if role == "primary":
        from motion_vlc_primary import main as primary_main
        primary_main()
    elif role == "secondary":
        from motion_vlc_secondary import main as secondary_main
        secondary_main()
    else:
        log(
            f"Invalid role '{role}'. Role must be 'primary' or 'secondary'.",
            "ERROR"
        )
        raise ValueError(
            f"Invalid role '{role}'. "
            "Role must be 'primary' or 'secondary'."
        )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("VLC application stopped by user.", "SYSTEM")
        print("Exiting.")
    except Exception as e:
        log(f"motion_vlc.py crashed: {e}", "ERROR")
        print("motion_vlc.py crashed:")
        traceback.print_exc()
        sys.exit(1)