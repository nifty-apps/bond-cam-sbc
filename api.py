import os
import requests
import time
import logging
from dotenv import load_dotenv

load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Get the BACKEND_API from the .env file
BACKEND_API = os.environ["BACKEND_API"]

GLOBAL_SETTINGS_API = f"{BACKEND_API}/settings"
DEVICE_BY_SERIAL_API = f"{BACKEND_API}/devices/serial"

# Global Wrapper to handle retries, timeouts, and error handling
def api_request(method, url, retries=3, delay=5, data=None):
    """General API request handler with retries."""
    for attempt in range(retries):
        try:
            if method.upper() == "GET":
                response = requests.get(url, timeout=10)
            elif method.upper() == "PUT":
                response = requests.put(url, json=data, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # Check for successful response
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error (attempt {attempt + 1}/{retries}): {e}")
        except ValueError as e:
            logger.error(f"Error parsing response JSON: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

        if attempt < retries - 1:
            logger.info(f"Retrying in {delay} seconds...")
            time.sleep(delay)
        else:
            logger.warning("Max retries reached. Returning None.")
            return None

# Function to get global settings
def get_global_settings():
    """Fetch global settings using the api_request wrapper."""
    return api_request("GET", GLOBAL_SETTINGS_API)

# Function to update device details
def update_device(serial, data):
    """Update device details using the api_request wrapper."""
    url = DEVICE_BY_SERIAL_API + f"/{serial}"
    response = api_request("PUT", url, data=data)
    
    if response:
        return response.get('data')
    else:
        logger.error("Failed to update device.")
        return None

