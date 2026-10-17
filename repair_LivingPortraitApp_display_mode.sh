
#!/bin/bash
set -euo pipefail

# Run as the regular LivingPortraitApp user:
# bash repair_LivingPortraitApp_display_mode.sh

USERNAME="$(id -un)"
HELPER="/usr/local/sbin/livingportrait-display-cmdline"
SUDOERS_FILE="/etc/sudoers.d/livingportrait-display"

log_info() {
    echo "[LivingPortraitApp] $1"
}

log_fail() {
    echo "[LivingPortraitApp] ERROR: $1" >&2
    exit 1
}

# Verify the helper has already been installed on this Pi.
if [[ ! -f "$HELPER" ]]; then
    log_fail "Display helper not found at $HELPER. Install display_cmdline_helper.py first."
fi

# Ensure the helper is owned by root and cannot be modified by the app user.
log_info "Setting display helper ownership and permissions..."
sudo chown root:root "$HELPER"
sudo chmod 755 "$HELPER"

# Normalize the installed helper to Unix LF line endings.
log_info "Normalizing display helper line endings..."
sudo sed -i 's/\r$//' "$HELPER"

# Configure passwordless sudo for this specific helper only.
log_info "Configuring display helper sudo permissions..."
SUDOERS_TEMP="$(mktemp)"
trap 'rm -f "$SUDOERS_TEMP"' EXIT

printf '%s ALL=(root) NOPASSWD: %s\n' \
    "$USERNAME" "$HELPER" > "$SUDOERS_TEMP"

sudo install -o root -g root -m 440 \
    "$SUDOERS_TEMP" "$SUDOERS_FILE"

# Validate the sudoers configuration.
if ! sudo visudo -cf "$SUDOERS_FILE"; then
    log_fail "Sudoers validation failed. Check $SUDOERS_FILE."
fi

# Verify the helper can be invoked without a password.
log_info "Checking passwordless helper permission..."

if ! sudo -n "$HELPER" </dev/null 2>/dev/null; then
    # Empty input should be rejected by the helper, but sudo must not
    # request a password. Verify the sudo rule if invocation fails.
    if ! sudo -n -l "$HELPER" >/dev/null 2>&1; then
        log_fail "Passwordless permission for the display helper could not be verified."
    fi
fi

log_info "Display helper permissions configured successfully."
log_info "Helper line endings normalized to LF."
log_info "No application files were downloaded or replaced."
log_info "No application services were restarted."

# Run with:
# bash repair_LivingPortraitApp_display_mode.sh
