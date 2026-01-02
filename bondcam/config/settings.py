"""Configuration management module for loading and accessing environment variables."""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Backend API configuration
BACKEND_API = os.environ.get("BACKEND_API", "")

# API endpoints
GLOBAL_SETTINGS_API = f"{BACKEND_API}/settings" if BACKEND_API else ""
DEVICE_BY_SERIAL_API = f"{BACKEND_API}/devices/serial" if BACKEND_API else ""

def get_backend_api():
    """Get the backend API URL from environment."""
    return BACKEND_API

def get_global_settings_api():
    """Get the global settings API endpoint."""
    return GLOBAL_SETTINGS_API

def get_device_by_serial_api():
    """Get the device by serial API endpoint."""
    return DEVICE_BY_SERIAL_API

