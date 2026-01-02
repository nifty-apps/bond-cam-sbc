"""API client for backend communication."""

import requests
import time
from bondcam.config.settings import (
    get_global_settings_api,
    get_device_by_serial_api
)
from bondcam.utils.logger import get_logger

logger = get_logger()

# Global Wrapper to handle retries, timeouts, and error handling
def api_request(method, url, delay=5, data=None):
    """General API request handler with infinite retries until connection is restored."""
    had_error = False
    attempt = 1
    
    while True:
        try:
            if method.upper() == "GET":
                response = requests.get(url, timeout=10)
            elif method.upper() == "PUT":
                response = requests.put(url, json=data, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # Check for successful response
            response.raise_for_status()
            
            # Print restoration message if previous attempt failed
            if had_error:
                logger.info("Connection restored successfully")
                
            return response.json()
        except requests.exceptions.RequestException as e:
            had_error = True
            logger.error(f"Request error (attempt {attempt}): {e}")
        except ValueError as e:
            logger.error(f"Error parsing response JSON: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

        logger.info(f"Retrying in {delay} seconds...")
        time.sleep(delay)
        attempt += 1

# Function to get global settings
def get_global_settings():
    """Fetch global settings using the api_request wrapper."""
    return api_request("GET", get_global_settings_api())

# Function to update device details
def update_device(serial, data):
    """Update device details using the api_request wrapper."""
    url = get_device_by_serial_api() + f"/{serial}"
    response = api_request("PUT", url, data=data)
    
    if response:
        return response.get('data')
    else:
        logger.error("Failed to update device.")
        return None

