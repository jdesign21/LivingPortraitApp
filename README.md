# LivingPortraitApp Instructions

## Overview

Welcome to the LivingPortraitApp project!

LivingPortraitApp enables you to display videos using VLC media player integration on a Raspberry Pi.

<p align="center">

<img src="https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/screenshots/Capture.PNG" width="30%" />

<img src="https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/screenshots/Capture2.PNG" width="30%" />

<img src="https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/screenshots/Capture3.PNG" width="30%" />

</p>

---

## 🚀 Version 2.0.0 Released

**LivingPortraitApp v2.0.0 is now available!**

Version 2.0.0 introduces major updates and changes to the application. Because of these changes, **version 2.0.0 requires a fresh installation**.

> ⚠️ **Important:** Existing LivingPortraitApp installations cannot be upgraded directly from version 1.x to version 2.0.0 using the built-in updater.

For version 2.0.0, install LivingPortraitApp on a fresh Raspberry Pi installation or perform a fresh installation according to the instructions below.

If you are upgrading from an earlier version, make sure to back up any videos or other files you want to keep before performing the fresh installation.

---

## Prerequisites

* A Raspberry Pi (any model that supports VLC)
* VLC media player installed on the Raspberry Pi
* Basic familiarity with terminal commands
* Access to the internet for downloading files

The installer will install the required software and configure LivingPortraitApp automatically.

---

## Setting Up the Raspberry Pi

If you are setting up a Raspberry Pi for the first time, the easiest method is to use Raspberry Pi Imager.

1. Download and install Raspberry Pi Imager on your computer.
2. Insert your Raspberry Pi microSD card into your computer.
3. Open Raspberry Pi Imager and select your Raspberry Pi model.
4. Select Raspberry Pi OS Lite (64-bit) as the operating system.
5. Select your microSD card as the storage device.
6. Before writing the image, open the operating system settings and configure:
   * Your Wi-Fi network and password
   * Your country/region
   * A username and password
   * Enable SSH so you can connect to the Raspberry Pi remotely
7. Write the operating system to the microSD card.
8. Insert the microSD card into the Raspberry Pi and power it on.
9. Once the Raspberry Pi has connected to your network, connect to it using SSH or a terminal application such as PuTTY.

---

## Installation

### Raspberry Pi 3B, 3B+, 4, Zero

Using PuTTY (or any terminal), run the following command to install LivingPortraitApp v2.0.0 on a fresh Raspberry Pi:

```bash
curl -sSL https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/setup_LivingPortraitApp_vlc.sh | bash
```

### Raspberry Pi 5

Using PuTTY (or any terminal), run the following command to install LivingPortraitApp v2.0.0 on a fresh Raspberry Pi 5:

```bash
curl -sSL https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/setup_LivingPortraitApp_vlc_pi5.sh | bash
```

---

## After Installation

Once the installer has finished, **reboot your Raspberry Pi** for all changes to take effect.

After rebooting, open a web browser on a computer or device connected to the same network and go to:

```text
http://[PI-IP]:5000
```

Replace `[PI-IP]` with the IP address of your Raspberry Pi.

For example:

```text
http://192.168.1.100:5000
```

The LivingPortraitApp web interface will open, and you can complete the initial configuration.


