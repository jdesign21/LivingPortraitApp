#!/bin/bash
set -euo pipefail
# Run as the regular LivingPortraitApp user: bash repair_LivingPortraitApp_display_mode.sh
REPO_URL="https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/fix-display-mode"
USERNAME="$(id -un)"
USER_HOME="$HOME"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
log_info() { echo "[LivingPortraitApp] $1"; }
log_fail() { echo "[LivingPortraitApp] ERROR: $1" >&2; exit 1; }

for file in pi/shared/display_helper.py pi/shared/vlc_helper.py pi/motion_vlc_primary.py pi/flask_ui/app.py; do
    curl -fsSL "$REPO_URL/$file" -o "$TEMP_DIR/$(basename "$file")" || log_fail "Download failed: $file"
done
curl -fsSL "$REPO_URL/pi/shared/display_cmdline_helper.py" -o "$TEMP_DIR/display_cmdline_helper.py" || log_fail "Download failed: display helper"
log_info "Installing restricted root-owned display helper..."
sudo install -o root -g root -m 755 "$TEMP_DIR/display_cmdline_helper.py" /usr/local/sbin/livingportrait-display-cmdline
sudo tee /etc/sudoers.d/livingportrait-display > /dev/null <<EOF
$USERNAME ALL=(root) NOPASSWD: /usr/local/sbin/livingportrait-display-cmdline
EOF
sudo chmod 440 /etc/sudoers.d/livingportrait-display
sudo visudo -cf /etc/sudoers.d/livingportrait-display || log_fail "Sudoers validation failed"
log_info "Updating LivingPortraitApp files..."
install -m 644 "$TEMP_DIR/display_helper.py" "$USER_HOME/shared/display_helper.py"
install -m 644 "$TEMP_DIR/vlc_helper.py" "$USER_HOME/shared/vlc_helper.py"
install -m 644 "$TEMP_DIR/motion_vlc_primary.py" "$USER_HOME/motion_vlc_primary.py"
install -m 644 "$TEMP_DIR/app.py" "$USER_HOME/flask_ui/app.py"
log_info "Restarting application services..."
sudo systemctl restart motion_vlc.service
sudo systemctl restart flask_ui.service
log_info "Repair completed."
