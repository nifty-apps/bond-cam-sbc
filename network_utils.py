from datetime import datetime, timezone
from api import update_device
import nmcli
import os
import time
from logger import get_logger

logger = get_logger()

# Disable sudo usage for nmcli - service should have NetworkManager permissions via polkit
# If running as root, sudo is not needed anyway
if os.geteuid() == 0:
    nmcli.disable_use_sudo()
else:
    # For non-root users, disable sudo if they have NetworkManager permissions
    # This requires proper polkit configuration
    try:
        nmcli.disable_use_sudo()
    except Exception as e:
        logger.warning(f"Could not disable sudo for nmcli: {e}. Sudo may be required.")

last_wifi_settings = None

def get_connected_network():
    """Get current Wi-Fi status by querying the system for the active SSID."""
    try:
        # Get all WiFi networks and find the one that's in use
        wifi_networks = nmcli.device.wifi()
        for network in wifi_networks:
            if network.in_use:
                return network.ssid
        
        # Fallback: check devices for connected WiFi
        devices = nmcli.device()
        for device in devices:
            if device.device_type == 'wifi' and device.state == 'connected':
                # The connection name is typically the SSID for WiFi
                return device.connection if device.connection else None
        return None
    except Exception as e:
        logger.error(f"Error getting current Wi-Fi status: {e}")
        return None

def get_available_networks():
    """Scan and return a list of available SSIDs in the area using nmcli."""
    try:
        # Get available WiFi networks
        wifi_networks = nmcli.device.wifi()
        
        # Extract SSIDs and deduplicate using a set
        networks = set()
        for network in wifi_networks:
            if network.ssid:  # Only add non-empty SSIDs
                networks.add(network.ssid)
        
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
    """Connect to a WiFi network using nmcli library."""
    try:
        # Connect to the Wi-Fi network using nmcli library
        # NetworkManager will automatically scan if needed
        nmcli.device.wifi_connect(ssid, password)
        logger.info(f"Successfully connected to network '{ssid}'")
        return True
    except Exception as e:
        logger.error(f"Error connecting to Wi-Fi network '{ssid}': {e}")
        return False

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