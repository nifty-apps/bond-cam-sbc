"""Device state management"""

from datetime import datetime, timezone
import subprocess
import re
from bondcam.api.client import update_device
from bondcam.devices.video import list_cameras
from bondcam.devices.audio import get_audio_devices
from bondcam.utils.logger import get_logger

logger = get_logger()


class DeviceManager:
    """Manages device state and operations"""
    
    def __init__(self, serial: str):
        """Initialize DeviceManager with device serial number.
        
        Args:
            serial: The device serial number
        """
        self.serial = serial
        self._device_info = None
    
    def get_serial_number(self) -> str:
        """Get the device serial number."""
        return self.serial
    
    def update_device_info(self) -> dict:
        """Update device info by scanning devices and sending to API.
        
        Returns:
            Updated device_info dictionary
        """
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
        self._device_info = update_device(self.serial, data)
        return self._device_info
    
    def get_device_info(self) -> dict:
        """Get current device info.
        
        Returns:
            Device info dictionary or None if not yet initialized
        """
        return self._device_info
    
    def get_stream_settings(self) -> dict:
        """Get stream settings with device paths resolved.
        
        Returns:
            Stream settings dictionary with resolved device paths
        """
        if self._device_info is not None:
            stream_settings = self._device_info.get('streamSettings', {})
            
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
    
    def check_for_reboot(self) -> bool:
        """Check if device should reboot.
        
        Returns:
            True if reboot was initiated, False otherwise
        """
        if self._device_info is not None:
            requires_reboot = self._device_info.get('requiresReboot')
            if requires_reboot:
                logger.info("Rebooting device")
                # Reset requiresReboot to False
                update_device(self._device_info['serial'], {'requiresReboot': False})
                # Reboot the device
                subprocess.run(["systemctl", "reboot"])
                return True
        return False


def get_serial_number():
    """Fetches the CPU serial number from /proc/cpuinfo.
    
    Returns:
        Serial number string
    """
    cmd_cpuinfo = "cat /proc/cpuinfo | grep Serial"
    result = subprocess.run(["bash", "-c", cmd_cpuinfo], stdout=subprocess.PIPE)
    serial_raw = result.stdout.decode('utf-8').split(' ')[-1]
    return re.sub(r"[\n\t\s]*", "", serial_raw)

