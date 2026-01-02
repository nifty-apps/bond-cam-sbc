#!/bin/bash
# Bondcam SBC Installation Script
# This script automates the installation of Bondcam on an SBC
# Run this script from the project root directory

set -e

# Get the directory where this script is located, then go to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Bondcam SBC Installation Script"
echo "================================"
echo ""
echo "Project directory: $PROJECT_ROOT"
echo ""

# Verify we're in the right place
if [ ! -f "$PROJECT_ROOT/requirements.txt" ] || [ ! -d "$PROJECT_ROOT/bondcam" ]; then
    echo "Error: This script must be run from the project root directory."
    echo "Expected to find requirements.txt and bondcam/ directory."
    exit 1
fi

# Update system packages
echo "Step 1: Updating system packages..."
sudo apt update
sudo apt install -y python3-pip git

# Install system dependencies
echo "Step 2: Installing system dependencies..."
sudo apt install -y \
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
  python3-pyudev || true

# Install Python dependencies
echo "Step 3: Installing Python dependencies..."
cd "$PROJECT_ROOT"
if [ -f requirements.txt ]; then
    pip3 install -r requirements.txt || pip3 install --user -r requirements.txt
    if [ $? -eq 0 ]; then
        echo "Python dependencies installed successfully."
    else
        echo "Warning: Some Python dependencies may have failed to install."
    fi
else
    echo "Error: requirements.txt not found!"
    exit 1
fi

# Configure environment
echo "Step 4: Configuring environment..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Created .env file from .env.example"
        echo "⚠️  Please edit .env and set your BACKEND_API before starting the service."
    else
        echo "Warning: .env.example not found. Creating empty .env file."
        touch .env
        echo "⚠️  Please create .env file with BACKEND_API configuration."
    fi
else
    echo ".env file already exists, skipping..."
fi

# Install systemd service
echo "Step 5: Installing systemd service..."
if [ ! -f "$PROJECT_ROOT/systemd/bondcam.service" ]; then
    echo "Error: systemd/bondcam.service not found!"
    exit 1
fi

# Update service file with actual project path
SERVICE_FILE="$PROJECT_ROOT/systemd/bondcam.service"
sudo cp "$SERVICE_FILE" /etc/systemd/system/bondcam.service

# Update WorkingDirectory in service file if needed
sudo sed -i "s|WorkingDirectory=.*|WorkingDirectory=$PROJECT_ROOT|g" /etc/systemd/system/bondcam.service
sudo sed -i "s|ExecStartPre=.*|ExecStartPre=/usr/bin/test -d $PROJECT_ROOT|g" /etc/systemd/system/bondcam.service

sudo systemctl daemon-reload
sudo systemctl enable bondcam

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Edit $PROJECT_ROOT/.env and set your BACKEND_API"
echo "2. Start the service: sudo systemctl start bondcam"
echo "3. Check status: sudo systemctl status bondcam"
echo "4. View logs: sudo journalctl -u bondcam -f"
echo ""
