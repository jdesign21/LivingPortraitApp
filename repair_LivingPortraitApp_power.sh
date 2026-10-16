#!/bin/bash
set -euo pipefail

# Add only the exact shutdown command required by LivingPortraitApp.
TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  echo "Run this script with sudo from the normal LivingPortraitApp account:"
  echo "  sudo bash repair_LivingPortraitApp_power.sh"
  exit 1
fi

if ! id "$TARGET_USER" >/dev/null 2>&1; then
  echo "User '$TARGET_USER' does not exist."
  exit 1
fi

SUDOERS_FILE="/etc/sudoers.d/livingportrait-power"
TEMP_FILE="$(mktemp)"
trap 'rm -f "$TEMP_FILE"' EXIT

printf '%s ALL=(root) NOPASSWD: /usr/sbin/shutdown -h now\n' "$TARGET_USER" > "$TEMP_FILE"
chmod 0440 "$TEMP_FILE"
visudo -cf "$TEMP_FILE" >/dev/null
install -o root -g root -m 0440 "$TEMP_FILE" "$SUDOERS_FILE"
visudo -c

echo "LivingPortraitApp shutdown permission installed for $TARGET_USER."
echo "Restart Flask with: sudo systemctl restart flask_ui"
