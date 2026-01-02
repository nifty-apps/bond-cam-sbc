#!/usr/bin/env python3
"""Main entry point for Bondcam streaming application."""

from bondcam.api.client import get_global_settings
from bondcam.core.device_manager import DeviceManager, get_serial_number
from bondcam.network.manager import NetworkManager
from bondcam.streaming.manager import StreamManager
from bondcam.utils.logger import get_logger
from gi.repository import GLib
import sys
import time
import traceback

logger = get_logger()


def main(args):
    """Main application entry point."""
    try:
        # Get device serial number
        serial = get_serial_number()

        # Initialize DeviceManager
        device_manager = DeviceManager(serial)

        # Initialize NetworkManager
        network_manager = NetworkManager()

        # Fetch global settings
        global_settings = get_global_settings()
        if global_settings:
            # Assigning values based on the response fields
            check_settings_every = global_settings['data']['checkSettingsEvery']
        else:
            # Provide a default value if global_settings is None
            check_settings_every = 5  # Default to 5 seconds

        # Set up periodic tasks
        def run_periodic_tasks():
            try:
                device_manager.update_device_info()
                network_manager.monitor_network_settings(device_manager)
                device_manager.check_for_reboot()
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
            if device_manager.get_device_info() is None:
                time.sleep(1)
                continue

            logger.info("Starting streaming process")
            break

        # Create and run the output connector
        # Pass DeviceManager's get_stream_settings method as the callable
        stream_manager = StreamManager('Bondcam', device_manager.get_stream_settings)
        stream_manager.run_pipeline()

        return 0

    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))

