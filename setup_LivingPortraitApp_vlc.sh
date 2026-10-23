
#!/bin/bash
set -e

# ============================================================
# Raspberry Pi 3B, 3B+, 4, Zero
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

# ============================================================
# Helper functions
# ============================================================

log_success() {
    echo -e "\e[32m✅ $1 completed successfully.\e[0m"
}

log_fail() {
    echo -e "\e[31m❌ $1 failed.\e[0m"
    exit 1
}

# ============================================================
# Installer information
# ============================================================

echo -e "\n============================================"
echo -e " LivingPortraitApp INSTALLER"
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
    vlc
    python3-gpiozero
    python3-vlc
    python3-venv
    mosquitto
    mosquitto-clients
    python3-paho-mqtt
    curl
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

sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

log_success "MQTT listener configuration"

# ============================================================
# LivingPortraitApp service permissions
# ============================================================

echo -e "\nSetting up LivingPortraitApp service permissions..."

sudo tee /etc/sudoers.d/livingportrait > /dev/null << EOF
$USERNAME ALL=(root) NOPASSWD: /usr/bin/systemctl enable mosquitto, /usr/bin/systemctl disable mosquitto, /usr/bin/systemctl start mosquitto, /usr/bin/systemctl stop mosquitto, /usr/bin/systemctl restart mosquitto, /usr/bin/systemctl restart motion_vlc, /usr/bin/systemctl restart flask_ui, /usr/bin/systemctl status motion_vlc, /usr/bin/systemctl status flask_ui
EOF

sudo chmod 440 /etc/sudoers.d/livingportrait

sudo visudo -cf /etc/sudoers.d/livingportrait \
    || log_fail "LivingPortraitApp service permissions validation"

log_success "LivingPortraitApp service permissions"

# ============================================================
# Python virtual environment
# ============================================================

echo -e "\nSetting up Python virtual environment..."

if [ ! -d "$VENV_PATH" ]; then
    python3 -m venv "$VENV_PATH" \
        || log_fail "Virtual environment creation"

    "$VENV_PATH/bin/pip" install --upgrade pip \
        || log_fail "pip upgrade"

    "$VENV_PATH/bin/pip" install flask paho-mqtt \
        || log_fail "Flask and MQTT pip installation"

    log_success "Flask virtual environment setup"
else
    log_success "Flask virtual environment already exists"
fi

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
    "$USER_HOME/flask_ui/templates"

log_success "Application directories"

# ============================================================
# Download application files
# ============================================================

echo -e "\nDownloading LivingPortraitApp files..."
echo -e "Release: $RELEASE"

TEMP_DIR=$(mktemp -d)
ZIP_FILE="$TEMP_DIR/LivingPortraitApp.zip"

cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

curl -fsSL \
    "https://github.com/jdesign21/LivingPortraitApp/archive/refs/tags/$RELEASE.zip" \
    -o "$ZIP_FILE" \
    || log_fail "Downloading LivingPortraitApp release"

python3 -m zipfile -e "$ZIP_FILE" "$TEMP_DIR" \
    || log_fail "Extracting LivingPortraitApp release"

PI_SOURCE=$(find "$TEMP_DIR" -type d -path "*/pi" -print -quit)

if [ -z "$PI_SOURCE" ]; then
    log_fail "Could not find pi folder in release"
fi

cp -r "$PI_SOURCE"/. "$USER_HOME"/ \
    || log_fail "Copying application files"

# Remove downloaded archive and extracted files.
rm -rf "$TEMP_DIR"
trap - EXIT

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

sudo install -o root -g root -m 755 \
    "$HELPER_SOURCE" "$HELPER_DEST" \
    || log_fail "Installing display command-line helper"

sudo sed -i 's/\r$//' "$HELPER_DEST" \
    || log_fail "Normalizing display helper line endings"

sudo chown root:root "$HELPER_DEST"
sudo chmod 755 "$HELPER_DEST"

SUDOERS_TEMP=$(mktemp)
trap 'rm -f "$SUDOERS_TEMP"' EXIT

printf '%s ALL=(root) NOPASSWD: %s\n' \
    "$USERNAME" "$HELPER_DEST" > "$SUDOERS_TEMP"

sudo install -o root -g root -m 440 \
    "$SUDOERS_TEMP" "$SUDOERS_FILE" \
    || log_fail "Installing display helper sudoers configuration"

sudo visudo -cf "$SUDOERS_FILE" \
    || log_fail "Display helper sudoers validation"

rm -f "$SUDOERS_TEMP"
trap - EXIT

log_success "Display configuration permissions"

# ============================================================
# Get application version
# ============================================================

echo -e "\nChecking application version..."

VERSION=$(curl -fsSL "$BASE_URL/version.txt") \
    || log_fail "Retrieving application version"

if [ -z "$VERSION" ]; then
    log_fail "Application version is empty"
fi

echo -e "\n📦 Installed LivingPortraitApp version $VERSION"

echo "$VERSION" > "$USER_HOME/version.txt"

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
ExecStart=$VENV_PATH/bin/python $USER_HOME/flask_ui/app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    log_success "Flask systemd service file created"
else
    echo "✔ flask_ui.service already exists"
fi

sudo systemctl daemon-reload
sudo systemctl enable flask_ui
sudo systemctl restart flask_ui

log_success "Flask UI service enabled and restarted"

# ============================================================
# motion_vlc systemd service
# ============================================================

echo -e "\nSetting up motion_vlc.service..."

if [ ! -f /etc/systemd/system/motion_vlc.service ]; then
    sudo tee /etc/systemd/system/motion_vlc.service > /dev/null << EOF
[Unit]
Description=Run motion_vlc.py at boot
After=network.target

[Service]
User=$USERNAME
ExecStart=/usr/bin/python3 $USER_HOME/motion_vlc.py
WorkingDirectory=$USER_HOME
StandardOutput=inherit
StandardError=inherit
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

    log_success "Systemd service file for motion_vlc created"
else
    echo "✔ motion_vlc.service already exists"
fi

sudo systemctl daemon-reload
sudo systemctl enable motion_vlc.service
sudo systemctl restart motion_vlc.service

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
    || log_fail "Shutdown and reboot sudoers validation"

log_success "Shutdown and reboot permissions configured"

# ============================================================
# Finished
# ============================================================

echo -e "\n============================================"
echo -e "🎉 LivingPortraitApp installation complete!"
echo -e "📦 Release installed: $RELEASE"
echo -e "📦 Application version: $VERSION"
echo -e "============================================"

echo -e "\nPlease reboot to apply all changes."
