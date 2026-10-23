
#!/bin/bash
set -e

# ============================================================
# Raspberry Pi 5
# LivingPortraitApp - INSTALLER
# ============================================================

# GitHub release to install
RELEASE="v2.0.0"
BASE_URL="https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/tags/$RELEASE/pi"

# ============================================================
# Get current username and home directory
# ============================================================

USERNAME=$(whoami)
USER_HOME="$HOME"
VENV_PATH="$USER_HOME/flask_venv"

# Temporary paths used by the installer
TEMP_DIR=""
SUDOERS_TEMP=""

# ============================================================
# Helper functions
# ============================================================

log_success() {
    echo -e "\e[32m$1 completed successfully.\e[0m"
}

log_fail() {
    echo -e "\e[31m$1 failed.\e[0m"
    exit 1
}

cleanup() {
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi

    if [ -n "$SUDOERS_TEMP" ] && [ -f "$SUDOERS_TEMP" ]; then
        rm -f "$SUDOERS_TEMP"
    fi
}

trap cleanup EXIT

# ============================================================
# Installer information
# ============================================================

echo -e "\n============================================"
echo -e " LivingPortraitApp INSTALLER"
echo -e " Raspberry Pi 5"
echo -e " Release: $RELEASE"
echo -e "============================================"

# ============================================================
# Update system
# ============================================================

echo -e "\nUpdating package list..."

sudo apt update -y || log_fail "apt update"

echo -e "\nUpgrading packages (this may take several minutes)..."

sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    || log_fail "apt upgrade"

log_success "System update"

# ============================================================
# Required packages
# ============================================================

echo -e "\nChecking required packages..."

REQUIRED_PKGS=(
    ffmpeg
    curl
    unzip
    vlc
    python3-gpiozero
    python3-vlc
    python3-venv
    libvlc-dev
    libpulse-dev
    mosquitto
    mosquitto-clients
    python3-paho-mqtt
)

MISSING_PKGS=()

for pkg in "${REQUIRED_PKGS[@]}"; do
    dpkg -s "$pkg" &>/dev/null || MISSING_PKGS+=("$pkg")
done

if [ ${#MISSING_PKGS[@]} -eq 0 ]; then
    log_success "All required packages already installed"
else
    echo "Installing missing packages: ${MISSING_PKGS[*]}"

    sudo apt install -y "${MISSING_PKGS[@]}" \
        || log_fail "Package installation"

    log_success "Package installation"
fi

# ============================================================
# MQTT listener configuration
# ============================================================

echo -e "\nSetting up MQTT listener configuration..."

sudo mkdir -p /etc/mosquitto/conf.d

sudo tee /etc/mosquitto/conf.d/listener.conf > /dev/null << 'EOF'
listener 1883
allow_anonymous true
EOF

sudo chmod 644 /etc/mosquitto/conf.d/listener.conf

sudo systemctl enable mosquitto \
    || log_fail "Enabling Mosquitto"

sudo systemctl restart mosquitto \
    || log_fail "Restarting Mosquitto"

log_success "MQTT listener configuration"

# ============================================================
# MQTT service permissions
# ============================================================

echo -e "\nSetting up MQTT service permissions..."

sudo tee /etc/sudoers.d/livingportrait > /dev/null << EOF
$USERNAME ALL=(root) NOPASSWD: /usr/bin/systemctl enable mosquitto, /usr/bin/systemctl disable mosquitto, /usr/bin/systemctl start mosquitto, /usr/bin/systemctl stop mosquitto, /usr/bin/systemctl restart mosquitto, /usr/bin/systemctl restart motion_vlc, /usr/bin/systemctl restart flask_ui, /usr/bin/systemctl start --no-block livingportrait-update.service
EOF

sudo chmod 440 /etc/sudoers.d/livingportrait

sudo visudo -cf /etc/sudoers.d/livingportrait \
    || log_fail "MQTT sudoers configuration"

log_success "MQTT service permissions"

# ============================================================
# Python virtual environment
# ============================================================

echo -e "\nSetting up Python virtual environment..."

if [ ! -d "$VENV_PATH" ]; then
    python3 -m venv "$VENV_PATH" \
        || log_fail "Virtual environment creation"
fi

if [ ! -x "$VENV_PATH/bin/python" ] || [ ! -x "$VENV_PATH/bin/pip" ]; then
    log_fail "Python virtual environment validation"
fi

"$VENV_PATH/bin/pip" install --upgrade pip \
    || log_fail "pip upgrade"

"$VENV_PATH/bin/pip" install flask paho-mqtt \
    || log_fail "Flask and MQTT pip installation"

log_success "Flask virtual environment setup"

# ============================================================
# Create directories
# ============================================================

echo -e "\nCreating directories..."

mkdir -p \
    "$USER_HOME/videos" \
    "$USER_HOME/pause_video" \
    "$USER_HOME/images" \
    "$USER_HOME/logs" \
    "$USER_HOME/shared" \
    "$USER_HOME/flask_ui/templates" \
    || log_fail "Application directory creation"

log_success "Application directories"

# ============================================================
# Download application files
# ============================================================

echo -e "\nDownloading LivingPortraitApp files..."
echo -e "Release: $RELEASE"

TEMP_DIR=$(mktemp -d) \
    || log_fail "Creating temporary directory"

ZIP_FILE="$TEMP_DIR/LivingPortraitApp.zip"
EXTRACT_DIR="$TEMP_DIR/extracted"

mkdir -p "$EXTRACT_DIR" \
    || log_fail "Creating extraction directory"

curl -fsSL \
    "https://github.com/jdesign21/LivingPortraitApp/archive/refs/tags/$RELEASE.zip" \
    -o "$ZIP_FILE" \
    || log_fail "Downloading LivingPortraitApp release"

python3 -m zipfile -e "$ZIP_FILE" "$EXTRACT_DIR" \
    || log_fail "Extracting LivingPortraitApp release"

PI_SOURCE=$(find "$EXTRACT_DIR" -type d -path "*/pi" -print -quit)

if [ -z "$PI_SOURCE" ] || [ ! -d "$PI_SOURCE" ]; then
    log_fail "Could not find pi folder in release"
fi

cp -r "$PI_SOURCE"/. "$USER_HOME"/ \
    || log_fail "Copying application files"

if [ ! -f "$USER_HOME/motion_vlc.py" ]; then
    log_fail "motion_vlc.py was not found after installation"
fi

chmod +x "$USER_HOME/motion_vlc.py" \
    || log_fail "Setting motion_vlc.py permissions"

log_success "LivingPortraitApp files downloaded"

# ============================================================
# Display command-line helper permissions
# ============================================================

echo -e "\nSetting up display configuration permissions..."

HELPER_SOURCE="$USER_HOME/shared/display_cmdline_helper.py"
HELPER_DEST="/usr/local/sbin/livingportrait-display-cmdline"
SUDOERS_FILE="/etc/sudoers.d/livingportrait-display"

if [ ! -f "$HELPER_SOURCE" ]; then
    log_fail "Display command-line helper not found: $HELPER_SOURCE"
fi

# Install the helper as a root-owned executable.
sudo install -o root -g root -m 755 \
    "$HELPER_SOURCE" "$HELPER_DEST" \
    || log_fail "Installing display command-line helper"

# Normalize the installed helper to Unix LF line endings.
sudo sed -i 's/\r$//' "$HELPER_DEST" \
    || log_fail "Normalizing display helper line endings"

sudo chown root:root "$HELPER_DEST"
sudo chmod 755 "$HELPER_DEST"

# Allow the application user to run only this helper without a password.
SUDOERS_TEMP=$(mktemp) \
    || log_fail "Creating display sudoers temporary file"

printf '%s ALL=(root) NOPASSWD: %s\n' \
    "$USERNAME" "$HELPER_DEST" > "$SUDOERS_TEMP"

sudo install -o root -g root -m 440 \
    "$SUDOERS_TEMP" "$SUDOERS_FILE" \
    || log_fail "Installing display helper sudoers configuration"

sudo visudo -cf "$SUDOERS_FILE" \
    || log_fail "Display helper sudoers configuration"

rm -f "$SUDOERS_TEMP"
SUDOERS_TEMP=""

log_success "Display configuration permissions"

# ============================================================
# Get application version
# ============================================================

echo -e "\nChecking application version..."

VERSION=$(curl -fsSL "$BASE_URL/version.txt") \
    || log_fail "Retrieving application version"

VERSION=$(echo "$VERSION" | tr -d '\r\n')

if [ -z "$VERSION" ]; then
    log_fail "Application version is empty"
fi

printf '%s\n' "$VERSION" > "$USER_HOME/version.txt" \
    || log_fail "Saving application version"

echo -e "\nInstalled LivingPortraitApp version: $VERSION"

# ============================================================
# Flask systemd service
# ============================================================

echo -e "\nSetting up Flask systemd service..."

if [ ! -f /etc/systemd/system/flask_ui.service ]; then
    sudo tee /etc/systemd/system/flask_ui.service > /dev/null << EOF
[Unit]
Description=Flask Web UI for Video Selector
After=network.target

[Service]
User=$USERNAME
WorkingDirectory=$USER_HOME/flask_ui
Environment=PYTHONPATH=$USER_HOME
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/1000
ExecStart=$VENV_PATH/bin/python $USER_HOME/flask_ui/app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    log_success "Flask systemd service file created"
else
    echo "Flask systemd service file already exists; leaving it unchanged."
fi

echo -e "\nSetting up LivingPortraitApp update worker service..."
sudo tee /etc/systemd/system/livingportrait-update.service > /dev/null << EOF
[Unit]
Description=LivingPortraitApp Update Worker
After=network.target

[Service]
Type=oneshot
User=$USERNAME
WorkingDirectory=$USER_HOME
Environment=HOME=$USER_HOME
Environment=PYTHONPATH=$USER_HOME
ExecStart=$VENV_PATH/bin/python -c "from shared.update_manager import run_pending_update; run_pending_update()"
TimeoutStartSec=infinity
StandardOutput=journal
StandardError=journal
EOF

sudo chmod 644 /etc/systemd/system/livingportrait-update.service
log_success "LivingPortraitApp update worker service configured"

sudo systemctl daemon-reload \
    || log_fail "Reloading systemd configuration"

sudo systemctl enable flask_ui \
    || log_fail "Enabling Flask UI service"

sudo systemctl restart flask_ui \
    || log_fail "Restarting Flask UI service"

log_success "Flask UI service enabled and restarted"

# ============================================================
# motion_vlc systemd service - Raspberry Pi 5
# ============================================================

echo -e "\nSetting up motion_vlc.service..."

if [ ! -f /etc/systemd/system/motion_vlc.service ]; then
    sudo tee /etc/systemd/system/motion_vlc.service > /dev/null << EOF
[Unit]
Description=Run motion_vlc.py at boot (Raspberry Pi 5 optimized)
After=network.target

[Service]
User=$USERNAME
WorkingDirectory=$USER_HOME
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native
ExecStart=/usr/bin/python3 $USER_HOME/motion_vlc.py
StandardOutput=append:$USER_HOME/logs/motion_vlc.log
StandardError=append:$USER_HOME/logs/motion_vlc.err
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

    log_success "motion_vlc systemd service file created for Pi 5"
else
    echo "motion_vlc.service already exists; leaving it unchanged."
fi

sudo systemctl daemon-reload \
    || log_fail "Reloading systemd configuration"

sudo systemctl enable motion_vlc.service \
    || log_fail "Enabling motion_vlc service"

sudo systemctl restart motion_vlc.service \
    || log_fail "Restarting motion_vlc service"

log_success "motion_vlc service enabled and restarted"

# ============================================================
# Shutdown and reboot permissions
# ============================================================

echo -e "\nSetting up shutdown and reboot permissions..."

POWER_SUDOERS_FILE="/etc/sudoers.d/livingportrait-reboot"

sudo tee "$POWER_SUDOERS_FILE" > /dev/null << EOF
$USERNAME ALL=(root) NOPASSWD: /usr/sbin/shutdown, /usr/sbin/reboot
EOF

sudo chmod 440 "$POWER_SUDOERS_FILE"

sudo visudo -cf "$POWER_SUDOERS_FILE" \
    || log_fail "Shutdown and reboot sudoers configuration"

log_success "Shutdown and reboot permissions"

# ============================================================
# Finished
# ============================================================

echo -e "\n============================================"
echo -e "LivingPortraitApp installation complete!"
echo -e "Release installed: $RELEASE"
echo -e "Application version: $VERSION"
echo -e "Raspberry Pi 5"
echo -e "============================================"

echo -e "\nPlease reboot to apply all changes."
