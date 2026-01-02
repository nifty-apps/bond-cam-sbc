# Bondcam SBC - Setup Guide

Complete setup guide for Bondcam on Single Board Computers (SBC).

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Detailed Setup](#detailed-setup)
- [Running the Application](#running-the-application)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Advanced Setup](#advanced-setup)

---

## Prerequisites

### Hardware Requirements
- Single Board Computer (tested on Orange Pi 5B)
- Camera(s) connected via USB or CSI
- Audio input device (optional)
- Network connectivity (WiFi or Ethernet)

### Software Requirements
- Ubuntu 22.04 or compatible Linux distribution
- Python 3.8 or higher
- Internet connection for initial setup

### System Dependencies

Install required system packages:

```bash
sudo apt update
sudo apt install -y \
  python3 \
  python3-pip \
  git \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav \
  gstreamer1.0-alsa \
  gstreamer1.0-pulseaudio \
  network-manager \
  python3-gi \
  python3-gi-cairo \
  gir1.2-gstreamer-1.0 \
  python3-pyudev
```

---

## Quick Start

For a quick installation on a fresh system:

```bash
# 1. Clone the repository
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/nifty-apps/bondcam-sbc.git
cd bondcam-sbc

# 2. Run the installation script
./scripts/install_service.sh

# 3. Configure environment
nano .env
# Set your BACKEND_API URL

# 4. Start the service
sudo systemctl start bondcam

# 5. Check status
sudo systemctl status bondcam
```

---

## Detailed Setup

### Step 1: System Preparation

Update your system and install base packages:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip git
```

### Step 2: Install System Dependencies

Install GStreamer and other required system packages (see [Prerequisites](#prerequisites) above).

### Step 3: Clone the Repository

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/nifty-apps/bondcam-sbc.git
cd bondcam-sbc
```

### Step 4: Install Python Dependencies

```bash
pip3 install -r requirements.txt
```

**Note:** If installing as a non-root user, add `--user` flag:
```bash
pip3 install --user -r requirements.txt
export PATH="$PATH:$HOME/.local/bin"
```

### Step 5: Configure Environment

Create your environment configuration:

```bash
cp .env.example .env
nano .env
```

Set the following variable:
```bash
BACKEND_API=https://your-backend-api-url.com
```

### Step 6: Install Systemd Service

```bash
# Create symlink to systemd service
sudo ln -s $(pwd)/systemd/bondcam.service /etc/systemd/system/bondcam.service

# Update service file with correct paths (if needed)
sudo sed -i "s|WorkingDirectory=.*|WorkingDirectory=$(pwd)|g" /etc/systemd/system/bondcam.service

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable bondcam

# Start the service
sudo systemctl start bondcam
```

### Step 7: Verify Installation

Check that the service is running:

```bash
sudo systemctl status bondcam
```

View logs:
```bash
sudo journalctl -u bondcam -f
```

---

## Running the Application

### As a Systemd Service (Recommended)

This is the recommended way for production use:

```bash
# Start the service
sudo systemctl start bondcam

# Stop the service
sudo systemctl stop bondcam

# Restart the service
sudo systemctl restart bondcam

# Check status
sudo systemctl status bondcam

# View logs (follow mode)
sudo journalctl -u bondcam -f

# View recent logs
sudo journalctl -u bondcam -n 100
```

### Direct Execution (Development/Testing)

For development or testing, you can run directly:

```bash
# From project root directory
cd ~/projects/bondcam-sbc
python3 -m bondcam.main
```

**Important:** You must run from the project root directory (where the `bondcam/` folder is located) so Python can find the package.

---

## Configuration

### Environment Variables

The application uses a `.env` file in the project root for configuration:

| Variable | Description | Required |
|----------|-------------|----------|
| `BACKEND_API` | Backend API base URL | Yes |

Example `.env` file:
```bash
BACKEND_API=https://api.example.com
```

### Service Configuration

The systemd service file is located at `systemd/bondcam.service`. Key settings:

- **Working Directory**: `/home/nifty/projects/bondcam-sbc`
- **User**: `nifty`
- **Restart Policy**: Always restart on failure
- **Logging**: Outputs to systemd journal

To modify the service, edit the file and reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart bondcam
```

---

## Troubleshooting

### Service Won't Start

1. **Check service status:**
   ```bash
   sudo systemctl status bondcam
   ```

2. **View error logs:**
   ```bash
   sudo journalctl -u bondcam -n 50
   ```

3. **Verify Python dependencies:**
   ```bash
   pip3 list | grep -E "(requests|python-dotenv|PyGObject|pyudev|nmcli)"
   ```

4. **Check environment file:**
   ```bash
   cat ~/projects/bondcam-sbc/.env
   ```

### Service Crashes on Startup

1. **Check for missing system dependencies:**
   ```bash
   which gst-launch-1.0
   which nmcli
   ```

2. **Verify camera/audio devices are accessible:**
   ```bash
   ls -la /dev/video*
   arecord -l
   ```

3. **Test Python module import:**
   ```bash
   cd ~/projects/bondcam-sbc
   python3 -c "import bondcam.main; print('OK')"
   ```

### Network Issues

1. **Check NetworkManager status:**
   ```bash
   sudo systemctl status NetworkManager
   ```

2. **Verify nmcli permissions:**
   ```bash
   sudo -u nifty nmcli device status
   ```

3. **Test API connectivity:**
   ```bash
   curl $(grep BACKEND_API ~/projects/bondcam-sbc/.env | cut -d'=' -f2)/settings
   ```

### Camera Not Detected

1. **List available cameras:**
   ```bash
   ls -la /dev/video*
   v4l2-ctl --list-devices
   ```

2. **Test camera access:**
   ```bash
   gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! autovideosink
   ```

### Viewing Logs

All logs are managed via systemd journalctl:

```bash
# Follow logs in real-time
sudo journalctl -u bondcam -f

# View last 100 lines
sudo journalctl -u bondcam -n 100

# View logs since boot
sudo journalctl -u bondcam -b

# View logs with timestamps
sudo journalctl -u bondcam --since "1 hour ago"
```

---

## Project Structure

```
bondcam-sbc/
├── bondcam/                    # Main Python package
│   ├── main.py                 # Application entry point
│   ├── api/                    # API communication module
│   │   └── client.py           # Backend API client
│   ├── streaming/              # Streaming functionality
│   │   └── manager.py         # GStreamer pipeline manager
│   ├── devices/                # Device management
│   │   ├── video.py           # Video device utilities
│   │   └── audio.py           # Audio device utilities
│   ├── network/                # Network management
│   │   └── manager.py         # WiFi/NetworkManager integration
│   ├── config/                 # Configuration management
│   │   └── settings.py        # Environment configuration
│   ├── core/                   # Core application logic
│   │   └── device_manager.py  # Device state management
│   └── utils/                  # Shared utilities
│       └── logger.py          # Logging utilities
├── systemd/                    # Systemd service files
│   └── bondcam.service        # Main service file
├── scripts/                    # Installation and utility scripts
│   └── install_service.sh     # Automated installation script
├── docs/                       # Documentation
│   ├── README.md              # This file
│   ├── image_setup.md         # Production image setup guide
│   └── installer_setup.md    # SD card installer guide
├── requirements.txt           # Python dependencies
└── .env.example              # Environment template
```

---

## Advanced Setup

### Production Image Setup

For creating production-ready images for deployment, see:
- [Image Setup Guide](docs/image_setup.md) - Creating production Ubuntu images
- [Installer Setup Guide](docs/installer_setup.md) - SD card installer preparation

### Development Setup

For development work:

1. **Clone and setup:**
   ```bash
   git clone https://github.com/nifty-apps/bondcam-sbc.git
   cd bondcam-sbc
   pip3 install -r requirements.txt
   ```

2. **Run in development mode:**
   ```bash
   python3 -m bondcam.main
   ```

3. **Enable debug logging:**
   Edit `bondcam/utils/logger.py` and change log level:
   ```python
   logging.basicConfig(level=logging.DEBUG, ...)
   ```

### Custom Service Configuration

To customize the service behavior, edit `systemd/bondcam.service`:

```bash
sudo nano systemd/bondcam.service
# Make your changes
sudo systemctl daemon-reload
sudo systemctl restart bondcam
```

---

## Support

For issues, questions, or contributions:
- Check the [Troubleshooting](#troubleshooting) section
- Review the [Advanced Setup](#advanced-setup) documentation
- Open an issue on GitHub

---

**Last Updated:** 2024
