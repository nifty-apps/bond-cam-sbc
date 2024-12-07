import os
import subprocess
import requests
import logging
from dbus import SystemBus, Interface
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BACKEND_API = os.environ["BACKEND_API"]

# API Endpoint
DEVICE_UPDATE_API_ENDPOINT = f"{BACKEND_API}/device/update"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# NetworkManager D-Bus interfaces and paths
interface_netman = "org.freedesktop.NetworkManager"
path_netman_settings = "/org/freedesktop/NetworkManager/Settings"
interface_settings = "org.freedesktop.NetworkManager.Settings"
interface_connection = "org.freedesktop.NetworkManager.Settings.Connection"


def list_all_connections():
    bus = SystemBus()
    settings_proxy = bus.get_object(interface_netman, path_netman_settings)
    settings = Interface(settings_proxy, interface_settings)
    connections = settings.ListConnections()
    for connection in connections:
        this_connection = bus.get_object(interface_netman, connection)
        this_connection_interface = Interface(this_connection, interface_connection)
        settings = this_connection_interface.GetSettings()

def set_networks_priorities(connection_type, priority):
    bus = SystemBus()
    settings_proxy = bus.get_object(interface_netman, path_netman_settings)
    settings = Interface(settings_proxy, interface_settings)
    connections = settings.ListConnections()
    for connection in connections:
        this_connection = bus.get_object(interface_netman, connection)
        this_connection_interface = Interface(this_connection, interface_connection)
        settings = this_connection_interface.GetSettings()
        if settings['connection']['type'] == connection_type:
            connection.SetAutoconnectPriority(priority)



def configure_network_priorities():
    """Configures network priorities for various network types."""
    print('Configuring connection priorities for network connections discovered:')
    list_all_connections()
    set_networks_priorities('ethernet', 0)
    set_networks_priorities('wifi', 10)
    set_networks_priorities('gsm', 50)
    set_networks_priorities('cdma', 50)



#==========================
# WiFi connection functions
#==========================

def modify_and_connect_wifi(wifi_settings, serial):
    available_networks = get_available_networks()
    connected_ssid = None
    all_networks = get_all_networks()

    for wifi in wifi_settings:
        ssid = wifi['ssid']
        logger.info(f"Attempting to connect to network '{ssid}'...")
        password = wifi['password']

        # Skip the connection if it's not available in the scanned list
        if ssid not in available_networks:
            logger.info(f"Network '{ssid}' not available in the area. Skipping...")
            continue

        network_info = next((net for net in all_networks if net[0] == ssid), None)
        active_connections = get_active_connections()

        if network_info:
            if ssid in active_connections:
                logger.info(f"Network '{ssid}' is already connected. Skipping...")
                connected_ssid = ssid
                break
            else:
                if should_update_wifi_connection(ssid, password):
                    if update_wifi_connection(ssid, password):
                        logger.info(f"Network settings updated for '{ssid}'")
                        if connect_to_wifi(ssid):
                            logger.info(f"Successfully connected to network '{ssid}'")
                            connected_ssid = ssid
                            break
                        else:
                            logger.warning(f"Failed to connect to network '{ssid}'. Trying next...")
                    else:
                        logger.warning(f"Failed to update network '{ssid}'. Trying next...")
                else:
                    if connect_to_wifi(ssid):
                        logger.info(f"Successfully connected to network '{ssid}'")
                        connected_ssid = ssid
                        break
                    else:
                        logger.warning(f"Failed to connect to network '{ssid}'. Trying next...")
        else:
            existing_connections = [net for net in all_networks if net[0] == ssid]
            if not existing_connections:
                if add_wifi_connection(ssid, password):
                    logger.info(f"Network settings added for '{ssid}'")
                    if connect_to_wifi(ssid):
                        logger.info(f"Successfully connected to network '{ssid}'")
                        connected_ssid = ssid
                        break
                    else:
                        logger.warning(f"Failed to connect to added network '{ssid}'. Trying next...")
            else:
                logger.warning(f"Network '{ssid}' already exists with UUID(s): {[net[1] for net in existing_connections]}. Skipping addition.")

    if connected_ssid:
        current_timestamp = datetime.now(timezone.utc).isoformat()
        update_wifi_status(serial, connected_ssid, current_timestamp)

def get_available_networks():
    """Scan and return a list of available SSIDs in the area."""
    scan_cmd = "iwlist wlan0 scanning | grep 'ESSID'"
    result = subprocess.run(["bash", "-c", scan_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode == 0:
        return [line.split(':')[1].replace('"', '').strip() for line in result.stdout.decode('utf-8').split('\n') if 'ESSID' in line]
    return []

def get_all_networks():
    """Get all configured networks."""
    check_cmd = "nmcli -g NAME,STATE connection show"
    result = subprocess.run(["bash", "-c", check_cmd], stdout=subprocess.PIPE)
    if result.returncode == 0:
        return [line.split(':') for line in result.stdout.decode('utf-8').strip().split('\n')]
    return []

def get_active_connections():
    """Get all active connections."""
    active_cmd = "nmcli -t -f NAME,DEVICE connection show --active"
    result = subprocess.run(["bash", "-c", active_cmd], stdout=subprocess.PIPE)
    if result.returncode == 0:
        return [line.split(':')[0] for line in result.stdout.decode('utf-8').strip().split('\n')]
    return []

def should_update_wifi_connection(ssid, password):
    get_password_cmd = f"sudo nmcli -s -g 802-11-wireless-security.psk connection show '{ssid}'"
    result = subprocess.run(["bash", "-c", get_password_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode == 0:
        current_password = result.stdout.decode('utf-8').strip()
        return current_password != password
    return True

def update_wifi_connection(ssid, password):
    modify_cmd = f"sudo nmcli connection modify '{ssid}' wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{password}'"
    result = subprocess.run(["bash", "-c", modify_cmd], stdout=subprocess.PIPE)
    return result.returncode == 0

def add_wifi_connection(ssid, password):
    add_cmd = f"sudo nmcli device wifi rescan && sudo nmcli connection add type wifi con-name '{ssid}' ssid '{ssid}' wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{password}'"
    result = subprocess.run(["bash", "-c", add_cmd], stdout=subprocess.PIPE)
    return result.returncode == 0

def connect_to_wifi(ssid):
    connect_cmd = f"sudo nmcli connection up '{ssid}'"
    try:
        subprocess.run(["bash", "-c", connect_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode('utf-8').strip() if e.stderr else str(e)
        logger.error(f"Error: {error_message}. Failed to connect to network '{ssid}'.")
        return False

def update_wifi_status(serial, connected_ssid, timestamp):
    data = {
        "serial": serial,
        "lastConnectedNetwork": connected_ssid,
        "lastUpdatedAt": timestamp
    }
    response = requests.put(DEVICE_UPDATE_API_ENDPOINT, data=data)
    if response.status_code == 200:
        logger.info(f"Successfully updated API with last connected network: {connected_ssid}")
    else:
        logger.error(f"Failed to update API. Status Code: {response.status_code}, Response: {response.text}")
