# Bondcam Image Setup  
## Orange Pi 5B — Ubuntu 22.04 XFCE

## 1. Purpose

This document describes how to prepare the **final production (eMMC) Ubuntu image** for Bondcam devices.

The resulting image:

- Runs Ubuntu 22.04 XFCE
- Auto‑logs in as user `nifty`
- Has Bondcam fully installed and enabled
- Has Tailscale pre‑installed
- Authenticates to Tailscale **only when real internet is available**
- Cleanly supports cloning to many devices

This image is written to eMMC using the **SD card installer** documented separately.

---

## 2. Design Principles (READ FIRST)

These rules matter and explain *why things are done this way*:

- ✅ Rename users, don’t recreate (UID stability)
- ✅ Bondcam must be **enabled in the image**, not at first boot
- ✅ Only per‑device state happens at first boot
- ✅ Network‑dependent logic waits for real internet
- ✅ One‑shot services must self‑delete
- ✅ Journald is preferred over file logging
- ✅ No secrets survive image cloning

---

## 3. Prerequisites

### Hardware
- Orange Pi 5B

### Software
- Official Orange Pi Ubuntu 22.04 XFCE image
- Bondcam source repository
- Tailscale ephemeral auth key
- Build machine with:
  - `losetup`
  - `mount`
  - `7z`

---

## 4. Mount the Base Image

All steps are done **inside the image**, not on a running device.

### 4.1 Extract the Image
```bash
7z x ubuntu-22.04-orangepi.img.7z
```

### 4.2 Attach Image as Loop Device

```bash
sudo losetup -Pf ubuntu-22.04-orangepi.img
lsblk
```

You’ll see something like:
```bash
NAME        MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
loop0        7:0    0  7.9G  1 loop
└─loop0p1    7:1    0    1G  0 part
└─loop0p2    7:2    0  6.8G  0 part
```
Assume it is /dev/loop0

### 4.3 Mount Image Filesystems

```bash
sudo mkdir -p /mnt/opimg
sudo mount /dev/loop0p2 /mnt/opimg
sudo mount /dev/loop0p1 /mnt/opimg/boot
```

Bind mounts (required for chroot)

```bash
sudo mount --bind /dev  /mnt/opimg/dev
sudo mount --bind /proc /mnt/opimg/proc
sudo mount --bind /sys  /mnt/opimg/sys
sudo mount --bind /run  /mnt/opimg/run
```

### 4.4 Chroot into the Image

```bash
sudo chroot /mnt/opimg /bin/bash
```

You are now inside the image.

---

## 5. User Setup (`orangepi → nifty`)

### 5.1 Rename User (Preserve UID/GID)

```bash
usermod -l nifty orangepi
groupmod -n nifty orangepi
usermod -d /home/nifty -m nifty
```

### 5.2 Password Handling

Choose **one**:

```bash
passwd nifty        # set known temporary password
```

Verify:

```bash
id nifty
```

UID **must be 1000**.

---

## 6. LightDM Auto‑Login Configuration

Remove Orange Pi defaults:

```bash
rm -f /etc/lightdm/lightdm.conf.d/22-orangepi-autologin.conf
```

Create nifty auto‑login:

```bash
cat > /etc/lightdm/lightdm.conf.d/30-nifty-autologin.conf <<'EOF'
[Seat:*]
autologin-user=nifty
autologin-user-timeout=0
user-session=xfce
EOF
```

---

## 7. Core System Packages

### 7.1 Update & Upgrade the System

```bash
apt update
apt upgrade -y
```

### 7.2 Install Core System Packages

```bash
apt install -y curl git python3 python3-pip pv p7zip-full
```

---

## 8. Bondcam Application Setup

### 8.1 Directory Layout

```
/home/nifty/projects/bondcam-sbc
```

Clone the Bondcam source repository:

```bash
mkdir -p /home/nifty/projects
git clone https://github.com/nifty-apps/bond-cam-sbc.git /home/nifty/projects/bondcam-sbc
chown -R nifty:nifty /home/nifty/projects
```

---

### 8.2 Python Dependencies

Dependencies **must** be installed during image build:

```bash
pip3 install --no-cache-dir \
  -r /home/nifty/projects/bondcam-sbc/requirements.txt
```

Why here:
- No internet dependency at boot
- systemd uses same Python environment
- deterministic builds

---

## 9. Bondcam systemd Service (ENABLED IN IMAGE)

```bash
nano /etc/systemd/system/bondcam.service
```

```ini
[Unit]
Description=Bondcam Streaming Service
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=nifty
Group=nifty
WorkingDirectory=/home/nifty/projects/bondcam-sbc
ExecStartPre=/usr/bin/test -d /home/nifty/projects/bondcam-sbc
ExecStart=/usr/bin/python3 bondcam_streaming.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable it **now**:

```bash
systemctl enable bondcam.service
```

This ensures Bondcam starts on *every boot*.

---

## 10. Tailscale Installation (Pre‑Install Only)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
systemctl enable tailscaled
```

❌ Do not authenticate here  
❌ Do not embed auth keys in image  

---

## 11. First‑Boot Local Setup (Offline)

Used only for **per‑device identity**.

```bash
nano /usr/local/bin/firstboot-local.sh
```

```bash
#!/bin/bash
set -e

MARK=/var/lib/firstboot-local.done
[[ -f "$MARK" ]] && exit 0

# Get the serial number of the device
SERIAL=$(
  cat /sys/firmware/devicetree/base/serial-number 2>/dev/null ||
  awk -F': ' '/^Serial/{print $2}' /proc/cpuinfo ||
  cat /proc/sys/kernel/random/uuid | cut -d- -f1
)

# Set the hostname of the device
hostnamectl set-hostname bondcam-$SERIAL

touch "$MARK"
systemctl disable firstboot-local.service
rm -f /etc/systemd/system/firstboot-local.service
systemctl daemon-reexec
```

Make executable:

```bash
chmod +x /usr/local/bin/firstboot-local.sh
```

### systemd Unit

```bash
nano /etc/systemd/system/firstboot-local.service
```

```ini
[Unit]
Description=First Boot Local Setup
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/firstboot-local.sh

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
systemctl enable firstboot-local.service
```

---

## 12. First‑Online Setup (Tailscale Authentication)

```bash
nano /usr/local/bin/first-online.sh
```

```bash
#!/bin/bash
set -e

AUTH_KEY="TSKEY-REPLACE-ME"
MARK=/var/lib/first-online.done
[[ -f "$MARK" ]] && exit 0

# Wait for real internet
for _ in {1..60}; do
  ping -c1 -W2 1.1.1.1 &>/dev/null && break
  sleep 5
done

ping -c1 -W2 1.1.1.1 &>/dev/null || exit 1

tailscale up \
  --authkey="$AUTH_KEY" \
  --hostname="$(hostname)" \
  --accept-dns \
  --accept-routes

# Clean secrets and self‑disable
sed -i 's/TSKEY-.*/AUTH_KEY=""/' /usr/local/bin/first-online.sh
touch "$MARK"
systemctl disable first-online.service
rm -f /etc/systemd/system/first-online.service
systemctl daemon-reexec
```

Make executable:

```bash
chmod +x /usr/local/bin/first-online.sh
```

### systemd Unit

```bash
nano /etc/systemd/system/first-online.service
```

```ini
[Unit]
Description=First Internet Provisioning
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/first-online.sh
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
systemctl enable first-online.service
```

---

## 13. Machine Identity Cleanup (MANDATORY)

Before exiting the image:

```bash
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
```

---

## 14. Exit, Unmount, Repack

```bash
exit
```

Unmount in reverse order:

```bash
sudo umount /mnt/opimg/{dev,proc,sys,run,boot}
sudo umount /mnt/opimg
sudo losetup -d /dev/loop0
```

Rename and repack the image:

```bash
mv ubuntu-22.04-orangepi.img bondcam-ubuntu-22.04-orangepi.img
7z a -mx=7 bondcam-ubuntu-22.04-orangepi.img.7z bondcam-ubuntu-22.04-orangepi.img
```

You can delete the .img file (optional):

```bash
rm bondcam-ubuntu-22.04-orangepi.img
```

You can now write the image to the eMMC using the SD card installer.

---

## 15. Expected Runtime Behavior

| Stage | Outcome |
|---|---|
First eMMC boot | Auto‑login as `nifty` |
Offline | Bondcam running |
Hostname | Set once |
Internet available | Tailscale authenticates |
Later reboots | Bondcam runs, no scripts |

---

## 16. Verification Checklist (AFTER INSTALLING THE IMAGE)

```bash
id nifty
hostname
systemctl status bondcam
journalctl -u bondcam.service
tailscale status
```

---

## 17. Common Pitfalls (Avoid These)

- ❌ Enabling Bondcam in firstboot
- ❌ Running `tailscale up` in image build
- ❌ Recreating users instead of renaming
- ❌ File‑based logging under systemd
- ❌ Leaving one‑shot services enabled

---

## 18. Final Status

✅ Bondcam image is deterministic  
✅ Safe to clone  
✅ Secure networking  
✅ Production‑grade  

---

## 19. Future Enhancements

- OTA updates
- Health watchdog
- Hardware availability checks
- Virtualenv isolation
- Secure boot chain

---

✅ **This document defines the final Bondcam production image.**