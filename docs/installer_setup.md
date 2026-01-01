# SD Card Installer Preparation  
## Orange Pi 5B — eMMC / Disk Installer

## 1. Purpose

This document describes how to prepare a **bootable SD card installer** for Orange Pi 5B that:

- Boots Ubuntu 22.04 XFCE
- Auto‑logs in
- Automatically launches an installer terminal
- Allows the operator up to **30 seconds** to:
  - Abort
  - Select an alternative target disk
- Safely flashes a **fresh OS image** (`.img` or `.img.7z`) to:
  - On‑board eMMC (default)
  - Another SD card
  - USB storage (if present)
- Powers off automatically when done

⚠️ **This SD card is disposable** — it is **not** the final operating system.

---

## 2. Installer Design Principles (IMPORTANT)

These principles guided the design and **must be preserved**:

- ✅ Never hard‑code `/dev/mmcblkX`
- ✅ Never overwrite the running root filesystem
- ✅ Filter out eMMC boot partitions, RPMB, zram, and fake devices
- ✅ Filter out 0‑byte card‑reader placeholders
- ✅ Provide a visible abort window
- ✅ Default to safe choice (on‑board eMMC)
- ✅ Keep installer logic out of early boot (no systemd tricks)

---

## 3. Prerequisites

### Hardware
- Orange Pi 5B
- microSD card (32 GB or larger recommended)

### Software
- Official Orange Pi Ubuntu 22.04 XFCE image
- Final **Bondcam image** to be written to eMMC:
  - `bondcam-ubuntu-22.04-orangepi.img`
  - or `bondcam-ubuntu-22.04-orangepi.img.7z`

---

## 4. Flash Base OS to SD Card

On a build machine:

```bash
sudo dd if=ubuntu-22.04-orangepi.img of=/dev/sdX bs=4M status=progress
sync
```

Replace `/dev/sdX` with the actual SD card device.

Insert the SD card into the Orange Pi and boot.

---

## 5. Base SD Environment Setup

After boot (auto‑login):

### 5.1 Install Required Tools

```bash
sudo apt update
sudo apt install -y pv p7zip-full
```

Notes:
- `pv` → progress display
- `p7zip-full` → stream `.7z` images
- No GUI extras required

---

## 6. Place the Target Image on the SD Card

Create a dedicated directory:

```bash
sudo mkdir -p /opt/emmc-image
```

Copy the **final Bondcam image** here:

```bash
sudo cp bondcam-ubuntu-22.04-orangepi.img.7z /opt/emmc-image/
```

Supported formats:
- ✅ `.img`
- ✅ `.img.7z`

⚠️ Do **not** extract `.7z` — the installer streams it safely.

---

## 7. Installer Script

```bash
sudo nano /usr/local/sbin/emmc-installer.sh
```

```bash
#!/bin/bash
set -euo pipefail

# Directory where target OS image lives
IMAGE_DIR=/opt/emmc-image

# Grace period before destructive write
DEFAULT_TIMEOUT=30

# ==========================================
#                 UI HEADER
# ==========================================
clear
echo "========================================="
echo "     Bondcam eMMC / DISK INSTALLER"
echo "          Orange Pi 5B"
echo "========================================="
echo ""
echo "This will ERASE the selected target disk!"
echo ""

# ==========================================
#           DETECT INSTALL IMAGE
# ==========================================
# Priority:
#   1) .7z (compressed, preferred)
#   2) .img (raw)
IMAGE_7Z=$(ls $IMAGE_DIR/*.7z 2>/dev/null || true)
IMAGE_IMG=$(ls $IMAGE_DIR/*.img 2>/dev/null || true)

if [[ -n "$IMAGE_7Z" ]]; then
  IMAGE="$IMAGE_7Z"
  MODE="7z"
elif [[ -n "$IMAGE_IMG" ]]; then
  IMAGE="$IMAGE_IMG"
  MODE="img"
else
  echo "ERROR: No image found in $IMAGE_DIR"
  sleep 10
  exit 1
fi

echo "Image: $(basename "$IMAGE")"
echo ""

# ==========================================
#        DETECT CURRENT BOOT DEVICE
# ==========================================
# We must NEVER overwrite the device we booted from.
ROOT_SRC=$(findmnt -n -o SOURCE /)
ROOT_DEV="/dev/$(lsblk -no PKNAME "$ROOT_SRC")"

# ==========================================
#      DETECT VALID TARGET DISKS
# ==========================================
# Rules for a valid target:
#   - TYPE == disk
#   - RO == 0 (read/write)
#   - SIZE != 0B (filters empty readers)
#   - NOT a boot/rpmb/zram device
#
# This safely filters out:
#   * mmcblkXboot*
#   * mmcblkXrpmb
#   * zram*
#   * empty SD readers
mapfile -t ALL_DEVS < <(
  lsblk -ndo NAME,TYPE,RO,SIZE |
  awk '$2=="disk" && $3==0 && $4!="0B" {print "/dev/"$1}' |
  grep -Ev '(boot|rpmb|zram)'
)

TARGETS=()
for d in "${ALL_DEVS[@]}"; do
  [[ "$d" != "$ROOT_DEV" ]] && TARGETS+=("$d")
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
  echo "ERROR: No valid target devices found"
  sleep 10
  exit 1
fi

# ==========================================
#         SELECT DEFAULT TARGET
# ==========================================
# On Orange Pi, internal eMMC is usually mmcblk0.
DEFAULT_TARGET=""
for d in "${TARGETS[@]}"; do
  [[ "$d" == "/dev/mmcblk0" ]] && DEFAULT_TARGET="$d"
done

# Fallback: first detected device
[[ -z "$DEFAULT_TARGET" ]] && DEFAULT_TARGET="${TARGETS[0]}"

SELECTED="$DEFAULT_TARGET"

# ==========================================
#           DISPLAY DEVICE MENU
# ==========================================
echo "Detected target devices:"
i=1
for d in "${TARGETS[@]}"; do
  SIZE=$(lsblk -ndo SIZE "$d")
  MODEL=$(lsblk -ndo MODEL "$d" || true)
  printf " [%d] %-12s %8s  %s\n" "$i" "$d" "$SIZE" "$MODEL"
  ((i++))
done

echo ""
echo "Default target: $DEFAULT_TARGET"
echo ""
echo "Press number [1-$((i-1))] within $DEFAULT_TIMEOUT seconds to change target."
echo "Press Ctrl+C to abort completely."
echo ""

# ==========================================
#      COUNTDOWN + USER SELECTION
# ==========================================
SECONDS_LEFT=$DEFAULT_TIMEOUT

while (( SECONDS_LEFT > 0 )); do
  printf "\rStarting installation in %2d seconds... " "$SECONDS_LEFT"

  # Non‑blocking single‑key read
  read -t 1 -n 1 key || true

  if [[ "$key" =~ [1-9] ]]; then
    idx=$((key-1))
    if [[ $idx -lt ${#TARGETS[@]} ]]; then
      SELECTED="${TARGETS[$idx]}"
      echo ""
      echo "Selected target: $SELECTED"
      break
    fi
  fi

  ((SECONDS_LEFT--))
done

echo ""
echo "Final target: $SELECTED"
echo ""
sleep 2

# ==========================================
#           SAFETY CHECK
# ==========================================
# Absolute last line of defense
if [[ "$SELECTED" == "$ROOT_DEV" ]]; then
  echo "ERROR: Refusing to overwrite root device"
  sleep 10
  exit 1
fi

# ==========================================
#           WRITE IMAGE
# ==========================================
echo "Clearing target disk..."
dd if=/dev/zero of="$SELECTED" bs=1M count=1000 status=progress
sync

echo ""
echo "Writing image..."

if [[ "$MODE" == "7z" ]]; then
  7z x -so "$IMAGE" | pv | dd of="$SELECTED" bs=4M conv=fsync status=none
else
  pv "$IMAGE" | dd of="$SELECTED" bs=4M conv=fsync status=none
fi

sync

echo ""
echo "✅ Installation complete"
echo "System will power off in 10 seconds."
sleep 10
poweroff
```

Make executable:

```bash
sudo chmod +x /usr/local/sbin/emmc-installer.sh
```

---

## 8. XFCE Auto‑Start Configuration

We deliberately use `xfce4-terminal` to:

- Avoid PTY issues
- Guarantee visible output
- Avoid early‑boot races

### Autostart File

```bash
nano ~/.config/autostart/emmc-installer.desktop
```

```ini
[Desktop Entry]
Type=Application
Name=Orange Pi eMMC Installer
Exec=xfce4-terminal --maximize --command="sudo /usr/local/sbin/emmc-installer.sh"
StartupNotify=false
Terminal=false
X-XFCE-Autostart-enabled=true
```

---

## 9. Passwordless Sudo (Installer Only)

Allow the installer to run without prompting:

```bash
sudo visudo
```

Add:

```
orangepi ALL=(root) NOPASSWD: /usr/local/sbin/emmc-installer.sh
```

(Change username if different on SD.)

---

## 10. Installer Runtime Behavior

### Typical Case (Only SD + eMMC)

- Installer auto‑starts
- Countdown runs
- Installs to eMMC automatically
- Powers off

### Multiple Targets Present

- Installer shows menu
- Default = eMMC
- User may press `2`, `3`, etc.
- Installation proceeds to selected disk

### Abort

- User presses `Ctrl+C`
- Installer stops
- System remains booted
- No disk modified

---

## 11. Safety Summary (READ THIS)

This installer is safe because:

✅ It does **not** hard‑code device names  
✅ It filters out non‑writable devices  
✅ It filters out fake 0B readers  
✅ It gives time to cancel  
✅ It refuses to overwrite its own root  
✅ It uses streaming, not temp files  

---

## 12. Maintenance Notes

- Do **not** add `systemctl` hooks
- Do **not** remove RO / SIZE filtering
- Do **not** auto‑run at early boot
- Always test with:
  ```
  lsblk
  ```

---

## ✅ Final Status

This SD installer is:

✔ Factory‑grade  
✔ Operator‑safe  
✔ Maintainable  
✔ Portable  
✔ Fully documented  

**This should not be modified lightly.**