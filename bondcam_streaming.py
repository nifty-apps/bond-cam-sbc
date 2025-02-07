#!/usr/bin/env python3
from api import get_global_settings, update_device
from audio_utils import get_audio_devices
from datetime import datetime, timezone
from dotenv import load_dotenv
from gi.repository import GLib
from network_utils import monitor_network_settings
from stream_manager import StreamManager
from video_utils import list_cameras
import re
import subprocess
import sys
import time
import traceback
from logger import get_logger

load_dotenv()
logger = get_logger()

device_info = None

def get_serial_number():
    """Fetches the CPU serial number."""
    cmd_cpuinfo = "cat /proc/cpuinfo | grep Serial"
    result = subprocess.run(["bash", "-c", cmd_cpuinfo], stdout=subprocess.PIPE)
    serial_raw = result.stdout.decode('utf-8').split(' ')[-1]
    return re.sub(r"[\n\t\s]*", "", serial_raw)

def update_device_info(serial):
    global device_info

    # Build connected_devices list
    connected_devices = []

    cameras = list_cameras()
    for camera in cameras:
        connected_devices.append(
            {
                'type': 'CAMERA',
                'name': camera['name'],
                'path': camera['path']
            }
        )
    audio_devices = get_audio_devices()
    for audio_device in audio_devices:
        connected_devices.append(
            {
                'type': 'AUDIO',
                'name': audio_device['name'],
                'path': audio_device['path']
            }
        )
    current_time = datetime.now(timezone.utc).isoformat()
    # Send device info to the integration endpoint
    data = {
        "connectedDevices": connected_devices,
        "lastOnlineAt": current_time
    }
    device_info = update_device(serial, data)

def get_stream_settings():
    if device_info is not None:
        stream_settings = device_info.get('streamSettings', {})
        
        # Build stream settings by replacing device names with paths
        connected_cameras = list_cameras()
        connected_audio = get_audio_devices()
        
        # Keep track of how many times we've seen each camera name
        camera_indices = {}
        
        # Replace camera names with their device paths in stream settings
        for stream in stream_settings.get('videoStreams', []):
            camera_name = stream['camera']
            # Initialize index counter for this camera name if not exists
            if camera_name not in camera_indices:
                camera_indices[camera_name] = 0
                
            # Find all cameras with matching name
            matching_cameras = [
                cam for cam in connected_cameras 
                if cam['name'] == camera_name
            ]
            
            # Get the camera at current index if available
            if camera_indices[camera_name] < len(matching_cameras):
                stream['camera'] = matching_cameras[camera_indices[camera_name]]['path']
                camera_indices[camera_name] += 1
            else:
                stream['camera'] = None
                
        # Replace audio device name with its device path
        audio_device = stream_settings.get('audioDevice')
        matched_audio = None
        for audio in connected_audio:
            if audio['name'] == audio_device:
                matched_audio = audio['path']
                break
        stream_settings['audioDevice'] = matched_audio

        return stream_settings
        
    else:
        return {}

def check_for_reboot():
    """Checks if the device should be rebooted."""
    if device_info is not None:
        requires_reboot = device_info.get('requiresReboot')
        if requires_reboot:
            logger.info("Rebooting device")
            # Reset requiresReboot to False
            update_device(device_info['serial'], {'requiresReboot': False})
            # Reboot the device
            subprocess.run(["sudo", "reboot"])

def main(args):
    try:
        # Initialize global variables
        global device_info
        check_settings_every = None

        serial = get_serial_number()

        # Fetch global settings
        global_settings = get_global_settings()
        if global_settings:
            # Assigning values to global variables based on the response fields
            check_settings_every = global_settings['data']['checkSettingsEvery']
        else:
            # Provide a default value if global_settings is None
            check_settings_every = 5  # Default to 5 seconds

        # Set up periodic tasks (every 5 seconds)
        def run_periodic_tasks():
            try:
                update_device_info(serial)
                monitor_network_settings(device_info)
                check_for_reboot()
                return True  # Keep timer running
            except Exception as e:
                logger.error(f"Error in periodic checks: {str(e)}")
                return True  # Keep timer running even on error

        GLib.timeout_add_seconds(check_settings_every, run_periodic_tasks)

        # Start initial tasks immediately
        run_periodic_tasks()

        # Wait for streaming to be ready
        while True:
            if global_settings is None:
                return 1

            # Ensure device_info is populated
            if device_info is None:
                time.sleep(1)
                continue

            logger.info("Starting streaming process")
            break

        # Create and run the output connector
        stream_manager = StreamManager('Bondcam', get_stream_settings)
        stream_manager.run_pipeline()

        return 0

    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main(sys.argv))