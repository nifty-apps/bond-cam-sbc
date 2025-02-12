from datetime import datetime, timezone
from api import update_device
import subprocess
import time
from logger import get_logger

logger = get_logger()

last_wifi_settings = None

def get_connected_network():
    """Get current Wi-Fi status by querying the system for the active SSID."""
    try:
        # Use iwgetid or nmcli to get the active SSID
        result = subprocess.run(['iwgetid', '-r'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        active_ssid = result.stdout.decode('utf-8').strip()
        return active_ssid if active_ssid else None
    except Exception as e:
        logger.error(f"Error getting current Wi-Fi status: {e}")
        return None

def get_available_networks():
    """Scan and return a list of available SSIDs in the area using iwlist."""
    try:
        result = subprocess.run(['iwlist', 'wlan0', 'scan'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = result.stdout.decode('utf-8')
        if result.returncode != 0:
            logger.error(f"Error scanning for available networks: {result.stderr.decode('utf-8')}")
            return []

        # Parse the output to extract the ESSIDs of all available networks
        networks = set()  # Use a set to automatically deduplicate
        for line in output.splitlines():
            if "ESSID:" in line:
                essid = line.split('ESSID:')[1].strip().strip('"')
                if essid:  # Only add non-empty SSIDs
                    networks.add(essid)

        # Convert back to sorted list for consistent output
        return sorted(list(networks))

    except Exception as e:
        logger.error(f"Error scanning for available networks: {e}")
        return []

def connect_to_preferred_network(preferred_networks, serial):
    """Connect to the preferred network if not already connected and available in the area."""

    connected_ssid = get_connected_network()
    logger.info(f"Current connected SSID: {connected_ssid}")

    available_networks = get_available_networks()
    logger.info(f"Available networks: {available_networks}")

    for wifi_network in preferred_networks:
        ssid = wifi_network['ssid']
        password = wifi_network['password']

        # Break if already connected to the preferred network
        if connected_ssid == ssid:
            logger.info(f"Already connected to network '{ssid}'.")
            break

        # Skip if network is not in the available coverage area
        if ssid not in available_networks:
            logger.warning(f"Network '{ssid}' not found in the area. Skipping...")
            continue
            
        # Attempt to connect to the network
        logger.info(f"Attempting to connect to network '{ssid}'...")
        if connect_to_wifi(ssid, password):
            logger.info(f"Successfully connected to network '{ssid}'")
            time.sleep(5)  # Wait for 5 seconds to ensure the connection is stable
            # Update the wifi status
            current_timestamp = datetime.now(timezone.utc).isoformat()
            update_wifi_status(serial, ssid, current_timestamp, preferred_networks)
            break
        else:
            logger.warning(f"Failed to connect to network '{ssid}'. Trying next...")

def connect_to_wifi(ssid, password):
    """Connect to a WiFi network using CLI tools (nmcli)."""
    try:
        # Force a rescan of Wi-Fi networks via NetworkManager
        subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)  # Allow time for the rescan
        
        # Connect to the Wi-Fi network using nmcli
        command = ['nmcli', 'dev', 'wifi', 'connect', ssid, 'password', password]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode == 0:
            logger.info(f"Successfully connected to network '{ssid}'")
            return True
        else:
            logger.error(f"Failed to connect to network '{ssid}': {result.stderr.decode('utf-8')}")
            return False

    except Exception as e:
        logger.error(f"Error connecting to Wi-Fi network '{ssid}': {e}")
        return False

def get_preferred_networks(serial):
    """Get the preferred networks from the API."""
    device_info = update_device(serial, {})
    wifi_settings = device_info.get("wifiSettings", [])
    preferred_networks = wifi_settings.get("preferredNetworks", [])
    return preferred_networks


def update_wifi_status(serial, connected_ssid, timestamp, preferred_networks):
    """Update WiFi status on the server."""
    data = {
        "serial": serial,
        "wifiSettings": {
            "lastConnectedNetwork": connected_ssid,
            "lastUpdatedAt": timestamp,
            "preferredNetworks": preferred_networks
        }
    }
    update_device(serial, data)

def monitor_network_settings(device_info):
    """Monitor network settings and update if necessary."""
    global last_wifi_settings

    # Get the latest network status from the API
    preferred_networks = device_info.get("wifiSettings", {}).get("preferredNetworks", [])
    last_connected = device_info.get("wifiSettings", {}).get("lastConnectedNetwork")

    # Check current network and update if different from lastConnectedNetwork
    current_network = get_connected_network()
    if current_network and current_network != last_connected:
        current_timestamp = datetime.now(timezone.utc).isoformat()
        update_wifi_status(device_info.get("serial"), current_network, current_timestamp, preferred_networks)

    # Only modify if wifiSettings has changed
    if preferred_networks != last_wifi_settings:
        if last_wifi_settings is None:
            logger.info(f"Initializing Wi-Fi settings: {preferred_networks}")
        else:
            logger.info(f"Wi-Fi settings changed. New settings: {preferred_networks}")
        connect_to_preferred_network(preferred_networks, device_info.get("serial"))
        last_wifi_settings = preferred_networks