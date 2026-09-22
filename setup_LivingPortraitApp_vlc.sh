#!/bin/bash
set -e

# ============================================================
# Raspberry Pi 3B, 3B+, 4, Zero
# LivingPortraitApp - INSTALLER
# ============================================================

# GitHub release to install
RELEASE="v1.0.0"
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
# Beta installer information
# ============================================================

echo -e "\n============================================"
echo -e " LivingPortraitApp INSTALLER"
echo -e " Release: $RELEASE"
echo -e "============================================"

# ============================================================
# Update system
# ============================================================

echo -e "\nUpdating package list..."
sudo apt update -y || log_fail "apt update failed"

echo -e "\nUpgrading packages (this may take several minutes)..."

# Show progress, avoid waiting for input
sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    || log_fail "apt upgrade failed"

log_success "System update completed"

# ============================================================
# Required packages
# ============================================================

echo -e "\nChecking required packages..."

REQUIRED_PKGS=(
    vlc
    python3-gpiozero
    python3-vlc
    python3-venv
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
        && log_success "Package installation" \
        || log_fail "Package installation"
fi

# ============================================================
# MQTT service permissions
# ============================================================

echo -e "\nSetting up MQTT service permissions..."

sudo tee /etc/sudoers.d/livingportrait > /dev/null << EOF
$USERNAME ALL=(root) NOPASSWD: /usr/bin/systemctl enable mosquitto, /usr/bin/systemctl disable mosquitto, /usr/bin/systemctl start mosquitto, /usr/bin/systemctl stop mosquitto
EOF

sudo chmod 440 /etc/sudoers.d/livingportrait

sudo visudo -cf /etc/sudoers.d/livingportrait \
    || log_fail "MQTT sudoers configuration"

log_success "MQTT service permissions configured"

# ============================================================
# Python virtual environment
# ============================================================

echo -e "\nSetting up Python virtual environment..."

if [ ! -d "$VENV_PATH" ]; then

    python3 -m venv "$VENV_PATH" \
        || log_fail "Virtual environment creation"

    "$VENV_PATH/bin/pip" install --upgrade pip

    "$VENV_PATH/bin/pip" install flask \
        || log_fail "Flask pip install"

    log_success "Flask virtual environment setup"

else

    log_success "Flask virtual environment already exists"

fi

# ============================================================
# Create directories
# ============================================================

echo -e "\nCreating directories..."

mkdir -p "$USER_HOME/videos" \
         "$USER_HOME/pause_video" \
         "$USER_HOME/images" \
         "$USER_HOME/logs" \
         "$USER_HOME/shared" \
         "$USER_HOME/flask_ui/templates"

# ============================================================
# Download application files
# ============================================================

echo -e "\nDownloading LivingPortraitApp files..."
echo -e "Release: $RELEASE"

TEMP_DIR=$(mktemp -d)
ZIP_FILE="$TEMP_DIR/LivingPortraitApp.zip"

# Download the complete GitHub release ZIP
curl -fsSL \
    "https://github.com/jdesign21/LivingPortraitApp/archive/refs/tags/$RELEASE.zip" \
    -o "$ZIP_FILE" \
    || {
        rm -rf "$TEMP_DIR"
        log_fail "Downloading LivingPortraitApp release"
    }

# Extract the release ZIP
python3 -m zipfile -e "$ZIP_FILE" "$TEMP_DIR" \
    || {
        rm -rf "$TEMP_DIR"
        log_fail "Extracting LivingPortraitApp release"
    }

# Find the pi folder inside the extracted release
PI_SOURCE=$(find "$TEMP_DIR" -type d -path "*/pi" -print -quit)

if [ -z "$PI_SOURCE" ]; then
    rm -rf "$TEMP_DIR"
    log_fail "Could not find pi folder in release"
fi

# Copy everything inside pi/ to the Raspberry Pi home directory
cp -r "$PI_SOURCE"/. "$USER_HOME"/ \
    || {
        rm -rf "$TEMP_DIR"
        log_fail "Copying application files"
    }

# Clean up temporary files
rm -rf "$TEMP_DIR"

log_success "LivingPortraitApp files downloaded"

# ============================================================
# Get application version
# ============================================================

VERSION=$(curl -fsSL "$BASE_URL/version.txt")

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

    log_success "Systemd service file for Flask created"

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
# Finished
# ============================================================

echo -e "\n============================================"
echo -e "🎉 LivingPortraitApp installation complete!"
echo -e "📦 Release installed: $RELEASE"
echo -e "📦 Application version: $VERSION"
echo -e "============================================"

echo -e "\nPlease reboot to apply all changes."
