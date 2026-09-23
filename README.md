# LivingPortraitApp Instructions

## Overview

Welcome to the LivingPortraitApp project!

This application enables you to display videos using VLC media player integration on a Raspberry Pi.

<p align="center">
  <img src="https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/screenshots/Capture.PNG" width="30%" />
  <img src="https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/screenshots/Capture2.PNG" width="30%" />
  <img src="https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/screenshots/Capture3.PNG" width="30%" />
</p>

---

## Prerequisites

* A Raspberry Pi (any model that supports VLC)
* VLC media player installed on the Raspberry Pi
* Basic familiarity with terminal commands
* Access to the internet for downloading files

---

## Installation

### Raspberry Pi 3B, 3B+, 4, Zero

Using PuTTY (or any terminal), run the following command to install everything on a fresh Raspberry Pi:

```bash
curl -sSL https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/setup_LivingPortraitApp_vlc.sh | bash
```

### Raspberry Pi 5

Using PuTTY (or any terminal), run the following command to install everything on a fresh Raspberry Pi 5:

```bash
curl -sSL https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/setup_LivingPortraitApp_vlc_pi5.sh | bash
```

### Update Code Only

Using PuTTY (or any terminal), run the following command to update code changes only:

```bash
curl -sSL https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/main/setup_LivingPortraitApp_vlc_UpdateOnly.sh | bash
```

---

## Beta Testing

The beta version contains the latest features and changes that are still being tested. Use the beta installer only if you want to test the upcoming release.

**Current Beta Release: `v2.0.0-beta.4`**

### Raspberry Pi 3B, 3B+, 4, Zero

Using PuTTY (or any terminal), run:

```bash
curl -sSL https://raw.githubusercontent.com/jdesign21/LivingPortraitApp/refs/heads/beta/setup_LivingPortraitApp_vlc-Beta.sh | bash
```

> **Note:** The beta version may contain bugs or changes that are not included in the current stable release.

---

Finish and reboot your Raspberry Pi for changes to take effect.
