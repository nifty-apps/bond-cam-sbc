#!/usr/bin/env python3
import os
from os import path, listdir, remove
from datetime import datetime
import time
import requests
import subprocess
import re
import traceback
from dotenv import load_dotenv
import NetworkManager
from dbus import SystemBus, Interface
import sys
import threading
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst, Gtk

from network_utils import configure_network_priorities, modify_and_connect_wifi
from audio_utils import select_audio_device

OUTPUT_WATCHDOG_TIMEOUT=0
VIDEO_FRAMERATE1=30
VIDEO_FRAMERATE2=30
CHECK_FILES_EVERY=None
VIDEO_DEVICE1=None
VIDEO_DEVICE2= None
AUTO_DETECT_USB_PORTS=1
CHECK_USB_EVERY=None
CHECK_SETTINGS_EVERY=None

class MyWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Timeout Example")
        self.label = Gtk.Label(label="Waiting for update...")
        self.add(self.label)

        # Add a timeout to call the update_label function every 2 seconds
        GLib.timeout_add_seconds(2, self.update_label)

    def update_label(self):
        self.label.set_text("Updated!")
        return True

interface_netman = "org.freedesktop.NetworkManager"
path_netman_settings = "/org/freedesktop/NetworkManager/Settings"

interface_settings = "org.freedesktop.NetworkManager.Settings"
interface_connection = "org.freedesktop.NetworkManager.Settings.Connection"

load_dotenv()

def get_serial_number():
    """Fetches the CPU serial number."""
    cmd_cpuinfo = "cat /proc/cpuinfo | grep Serial"
    result = subprocess.run(["bash", "-c", cmd_cpuinfo], stdout=subprocess.PIPE)
    serial_raw = result.stdout.decode('utf-8').split(' ')[-1]
    return re.sub(r"[\n\t\s]*", "", serial_raw)

serial = get_serial_number()

# Keep the API URL in the .env or configuration file
BACKEND_API = os.environ["BACKEND_API"]

# API Endpoints
INTEGRATION_ENDPOINT = f"{BACKEND_API}/device/configure"
CONFIGURE_API = f"{BACKEND_API}/settings"

# Fetch configuration from INTEGRATION_ENDPOINT API (requires serial)
def fetch_integration_config(serial):
    try:
        response = requests.post(INTEGRATION_ENDPOINT, data={"serial": serial})
        response.raise_for_status()
        config_data = response.json().get('data', {}).get('device', {}).get('deviceSettings', {})
        return config_data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching integration config: {e}")
        return None

# Fetch additional configuration from CONFIGURE_API (no serial required)
def fetch_configure_api():
    try:
        response = requests.get(CONFIGURE_API)
        response.raise_for_status()
        config_data = response.json().get('data', {})
        return config_data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching configuration API data: {e}")
        return None

# Fetch values directly from the Integration API (for specific settings)
def fetch_integration_values(serial):
    global VIDEO_DEVICE1, VIDEO_DEVICE2
    integration_config = fetch_integration_config(serial)
    
    if integration_config:
        VIDEO_DEVICE1 = integration_config['videoDevice1']
        VIDEO_DEVICE2 = integration_config['videoDevice2']

def fetch_configure_api():
    try:
        response = requests.get(CONFIGURE_API)
        response.raise_for_status()
        config_data = response.json()
        return config_data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching configuration API data: {e}")
        return None

# Fetch values from the Configuration API and assign them to global variables
configure_api_data = fetch_configure_api()

if configure_api_data:
    # Assigning values to global variables based on the response fields
    CHECK_FILES_EVERY = configure_api_data['checkFilesEvery']
    CHECK_SETTINGS_EVERY = configure_api_data['checkSettingsEvery']
    CHECK_USB_EVERY = configure_api_data['checkUsbEvery']


os.environ["GST_DEBUG"] = '2,flvmux:1'

import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst

device_slot = []
current_settings1 = None
current_settings2 = None
current_global_settings = None
output = None
serial = None
skip_cameras_val=0

def check_wifi_and_apply_changes():
    try:
        # Assuming 'serial' is defined or obtained elsewhere
        serial = get_serial_number()  
        req3 = requests.post(INTEGRATION_ENDPOINT, data={"serial": serial})
        req_data = req3.json()
        wifi_settings = req_data['data']['device']['wifiSettings']

        do_reset_wifi = req_data['data']['device'].get('doResetWifi', False)

        # Check if doResetWifi is true before modifying the wifi settings
        if do_reset_wifi:
            modify_and_connect_wifi(wifi_settings, serial)
    
    except Exception as e:
        print(f"An error occurred: {e}")

def run_periodically(CHECK_SETTINGS_EVERY):
    while True:
        check_wifi_and_apply_changes()
        time.sleep(CHECK_SETTINGS_EVERY)


def get_usb_devices():
    cmd_devices = """v4l2-ctl --list-devices"""
    devicesstr = subprocess.run(["bash", "-c", cmd_devices], stdout=subprocess.PIPE)
    devices = devicesstr.stdout.decode('utf-8')
    d_counter = 0
    l_devices = []
    for d in devices.split('\n\n'):
        if len(d) > 0:
            d_counter += 1
            d_name = d.split('\n\t')[0]
            d_address = d.split('\n\t')[1]
            l_devices.append(d_address)
            # print(f'Found device #{d_counter}: address {d_address} name {d_name}')


    if d_counter > 2:
        # print(f'More than 2 cameras found, we would use last 2')
        d_counter = 2
        l_devices=l_devices[:2]
    elif d_counter == 2:
        pass
        # print(f'All 2 cameras found automatically')
    elif d_counter == 0:
        # print('Unable to find cameras')
        pass
    elif d_counter == 1:
        # print('Only 1 camera found')
        pass
    return l_devices, d_counter

def cb_check_usb(output):
    try:
        print('Callback: performing USB check')
        l_devices_new, d_counter_new = get_usb_devices()
        #Filling device slots:
        for device in l_devices_new:
            print(f'Checking device {device}. Device slot list is {device_slot}')
            if (device not in device_slot) and len(device_slot)<2:
                print(f'Appending device {device} to slot list.')
                device_slot.append(device)
                camera_num = len(device_slot)-1
                output.set_usb_camera_address(device, camera_num)
                output.connect_usb_camera(camera_num)
            elif (device == device_slot[0]) and not output.source_bins[0]:
                print(f'Connecting device {device} back to slot #{0}')
                output.connect_usb_camera(0)
            elif (device == device_slot[1]) and not output.source_bins[1]:
                print(f'Connecting device {device} back to slot #{1}')
                output.connect_usb_camera(1)

    except Exception as ex:
        print(f'Exception at USB check callback: {str(ex)}')
        return True
    return True

def get_cameras_settings():
    try:
        req3 = requests.post(INTEGRATION_ENDPOINT, data={"serial": serial})
        req_data = req3.json()

        settings1 = {'bitrate': req_data['data']['device']['channels']['camera1']['bitrate'] * 1000,
                     'white_balance': req_data['data']['device']['channels']['camera1']['whiteBalance']}
        settings2 = {'bitrate': req_data['data']['device']['channels']['camera2']['bitrate'] * 1000,
                     'white_balance': req_data['data']['device']['channels']['camera2']['whiteBalance']}
        global_settings = {'is_reserve': req_data['data']['device']['isReserve']}
        wifi_settings = req_data['data']['device']['wifi_settings']
        do_renew_wifi = req_data['data']['device']['doResetWifi']

    except Exception as e:
        exc_tb = sys.exc_info()
        fname = exc_tb.tb_frame.f_code.co_filename
        line_num = exc_tb.tb_lineno
        print(f"An error occurred in file '{fname}' at line {line_num}: {e}")
        traceback.print_exc()
        settings1, settings2, global_settings, wifi_settings, do_renew_wifi = current_settings1, current_settings2, current_global_settings, current_wifi_settings, False
    return settings1, settings2, global_settings, wifi_settings, do_renew_wifi

def cb_check_settings(b):
    global current_settings1, current_settings2, current_global_settings, current_wifi_settings
    try:
        print('Callback: performing check of settings')
        settings1, settings2, global_settings, wifi_settings, do_renew_wifi = get_cameras_settings()
        if (len(set(current_settings1.items()) ^ set(settings1.items())) > 0) or (len(set(current_settings2.items()) ^ set(settings2.items())) > 0) :
            print('Camera settings changed. Adjusting')
            output.modify_settings(settings1, settings2)
            current_settings1 = settings1
            current_settings2 = settings2
        else:
            pass
        if len(set(current_global_settings.items()) ^ set(global_settings.items())) > 0:
            print('Device settings changed. Adjusting')
            output.modify_device_settings(global_settings)
            current_global_settings = global_settings
        else:
            pass
    except Exception as ex:
        print(f'Exception at settings check callback: {str(ex)}')
        return True
    return True

def remove_pipeline(pipeline, label):
    print(f'Pipeline "{label}" is removing')

    pipeline.send_event(Gst.Event.new_eos())
    time.sleep(0.1)

    state = pipeline.set_state(Gst.State.READY)
    time.sleep(0.5)
    state = pipeline.set_state(Gst.State.NULL)
    time.sleep(0.5)

    pipeline = None
    time.sleep(0.5)
    print(f'Removed pipeline "{label}"')

class output_connector:
    def __init__(self, label, rtmp_path1=None, rtmp_path2=None, settings1=None, settings2=None, global_settings=None):
        self.pipeline = None
        self.bus = None
        self.source_bins = [None, None]
        self.source_bin_strs = ['', '']
        self.compositors = []
        self.label = label
        self.watchdog_timeout = OUTPUT_WATCHDOG_TIMEOUT
        self.rtmp_path1 = rtmp_path1
        self.rtmp_path2 = rtmp_path2
        self.settings1 = settings1
        self.settings2 = settings2
        self.global_settings = global_settings
        self.devices = [None, None]

        silence_audio = global_settings['silence_audio'] if global_settings else True
        self.audioDevice = select_audio_device(silence_audio)
        self.with_audio = self.audioDevice is not None

        self.launch_pipeline()

    def launch_pipeline(self):
        # Check if the pipeline exists and clean it up if needed
        if self.pipeline:
            print(f'Calling async pipeline destruction for output_connector class "{self.label}"')
            self.pipeline.call_async(remove_pipeline, self.label)
            time.sleep(5)
            print(f'End of calling async pipeline destruction for output_connector class "{self.label}"')

        # Start building the GStreamer command with conditional elements
        gcommand = ""

        # Configure camera1 pipeline if available
        if self.rtmp_path1 and self.settings1:
            camera1_bitrate = self.settings1['bitrate']
            gcommand += f"""
                videotestsrc pattern=0 is-live=1 ! videoconvert ! video/x-raw,width=1920,height=1080! source_compositor1.sink_0    
                input-selector name=source_compositor1 sync-mode=1 ! videoconvert ! video/x-raw,format=NV12 !  
                mpph264enc name=encoder1 profile=main qos=1 header-mode=1 profile=main bps={camera1_bitrate} bps-max={camera1_bitrate + 1000000} rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee1_{self.label} ! 
                queue ! flvmux name=mux streamable=1 ! watchdog timeout={self.watchdog_timeout} ! rtmp2sink sync=0 name=rtmpsink1{self.label} location="{self.rtmp_path1}"
            """

        # Configure camera2 pipeline if available
        if self.rtmp_path2 and self.settings2:
            camera2_bitrate = self.settings2['bitrate']
            gcommand += f"""
                videotestsrc pattern=0 is-live=1 ! videoconvert ! video/x-raw,width=1920,height=1080! source_compositor2.sink_0 
                input-selector name=source_compositor2 sync-mode=1 ! videoconvert ! video/x-raw,format=NV12 !  
                mpph264enc name=encoder2 profile=main qos=1 header-mode=1 profile=main bps={camera2_bitrate} bps-max={camera2_bitrate + 1000000} rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee2_{self.label} ! 
                queue ! flvmux name=mux2 streamable=1 ! watchdog timeout={self.watchdog_timeout} ! rtmp2sink sync=0 name=rtmpsink2{self.label} location="{self.rtmp_path2}"
            """

        # Set up audio input pipeline
        if self.with_audio:
            audio_input = f'alsasrc device={self.audioDevice} ! audioresample ! audio/x-raw,rate=48000 ! voaacenc bitrate=96000 ! audio/mpeg ! aacparse ! audio/mpeg, mpegversion=4'
        else:
            audio_input = f'audiotestsrc is-live=1 wave=silence ! audioresample ! audio/x-raw,rate=48000 ! voaacenc bitrate=96000 ! audio/mpeg ! aacparse ! audio/mpeg, mpegversion=4'

        # Conditionally link audio to mux elements based on video availability
        if self.rtmp_path1 and self.rtmp_path2:
            # Both cameras are available, link audio to both mux and mux2
            gcommand += f"{audio_input} ! tee name=audiotee ! queue ! mux. audiotee. ! queue ! mux2."
        elif self.rtmp_path1:
            # Only camera1 is available, link audio to mux only
            gcommand += f"{audio_input} ! queue ! mux."
        elif self.rtmp_path2:
            # Only camera2 is available, link audio to mux2 only
            gcommand += f"{audio_input} ! queue ! mux2."

        print(f'GStreamer pipeline: {gcommand}\n')
        self.pipeline = Gst.parse_launch(gcommand)

        # Retrieve and configure compositors for each active camera
        if self.rtmp_path1:
            self.compositors.append(self.pipeline.get_by_name('source_compositor1'))
        if self.rtmp_path2:
            self.compositors.append(self.pipeline.get_by_name('source_compositor2'))

        # Set the pipeline to the PLAYING state
        self.pipeline.set_state(Gst.State.PLAYING)
        self.modify_settings(self.settings1, self.settings2)
        self.modify_device_settings(self.global_settings)

    def connect_usb_camera(self, camera_num):
        if self.source_bins[camera_num]:
            print(f"!!! Error: USB source bin {camera_num} wasn't destroyed")
            self.disconnect_usb_camera(camera_num)
            time.sleep(0.5)
        self.source_bins[camera_num] = Gst.parse_bin_from_description(self.source_bin_strs[camera_num], True)
        print(f'Searching for compositor source_compositor{camera_num+1}')
        pad1 = self.compositors[camera_num].get_request_pad('sink_%u')
        if not pad1:
            print(f'Unable to retrieve sink pad from compositor source_compositor{camera_num+1}')
        self.pipeline.add(self.source_bins[camera_num])
        self.source_bins[camera_num].sync_state_with_parent()
        src1 = self.source_bins[camera_num].get_static_pad('src')
        src1.link(pad1)
        self.compositors[camera_num].set_property("active-pad", pad1)
        print(f'Camera {camera_num} is connected back')
        return True

    def set_usb_camera_address(self, address, camera_num):
        self.devices[camera_num] = address
        self.source_bin_strs[camera_num] = f'v4l2src do-timestamp=1 device={self.devices[camera_num]} ! image/jpeg,framerate={VIDEO_FRAMERATE1 if camera_num == 0 else VIDEO_FRAMERATE2}/1,width=1920,height=1080 ! queue ! mppjpegdec ! watchdog timeout=1000 '
        print(f'Camera {camera_num} address set to {address}. Bin pipeline is {self.source_bin_strs[camera_num]}')


    def disconnect_usb_camera(self, camera_num):
        pad10 = self.compositors[camera_num].get_static_pad('sink_0')
        self.compositors[camera_num].set_property("active-pad", pad10)

        pad11 = self.compositors[camera_num].get_static_pad('sink_1')
        compositor1_sink_0_peer = pad11.get_peer()
        if compositor1_sink_0_peer:
            compositor1_sink_0_peer.unlink(pad11)

        if self.source_bins[camera_num]:
            self.source_bins[camera_num].set_state(Gst.State.NULL)
            self.pipeline.remove(self.source_bins[camera_num])
            self.source_bins[camera_num] = None
        return True 

    def modify_settings(self, settings1, settings2):
        print(f'Using new settings for camera1: {settings1} and camera2: {settings2}')
        if self.devices[0]:
            encoder1 = self.pipeline.get_by_name('encoder1')
            encoder1.set_property('bps', settings1['bitrate'])
            encoder1.set_property('bps-max', settings1['bitrate']+1000000)
            disable_auto_white_balance_cmd1 = f'v4l2-ctl --device {self.devices[0]} -c white_balance_temperature_auto=0'
            disable_auto_white_balance1 = subprocess.run(["bash", "-c", disable_auto_white_balance_cmd1], stdout=subprocess.PIPE)
            set_white_balance_cmd1 = f'v4l2-ctl --device {self.devices[0]} -c white_balance_temperature={settings1["white_balance"]}'
            set_white_balance1 = subprocess.run(["bash", "-c", set_white_balance_cmd1], stdout=subprocess.PIPE)
        self.settings1 = settings1
        if self.devices[1]:
            encoder2 = self.pipeline.get_by_name('encoder2')
            encoder2.set_property('bps', settings2['bitrate'])
            encoder2.set_property('bps-max', settings2['bitrate']+1000000)
            disable_auto_white_balance_cmd2 = f'v4l2-ctl --device {self.devices[1]} -c white_balance_temperature_auto=0'
            disable_auto_white_balance2 = subprocess.run(["bash", "-c", disable_auto_white_balance_cmd2], stdout=subprocess.PIPE)
            set_white_balance_cmd2 = f'v4l2-ctl --device {self.devices[1]} -c white_balance_temperature={settings2["white_balance"]}'
            set_white_balance2 = subprocess.run(["bash", "-c", set_white_balance_cmd2], stdout=subprocess.PIPE)
        self.settings2 = settings2

    def modify_device_settings(self, global_settings):
        print(f'Using new global settings for device: {global_settings}')

        #Process is_reserve. When true, we don't need to stream anymore
        if global_settings['is_reserve']:
            print('isReserve has been changed, relaunching to enable stand by mode')
            exit(5)

        self.global_settings = global_settings


    def format_location_callback1(self, splitmux, fragment_id):
        now = datetime.now()
        file_path=f'{self.save_path}stream1_{now.isoformat()}.mp4'
        print(f'Stream 1 is starting to record into a new videofile {file_path}')
        return file_path

    def format_location_callback2(self, splitmux, fragment_id):
        now = datetime.now()
        file_path=f'{self.save_path}stream2_{now.isoformat()}.mp4'
        print(f'Stream 2 is starting to record into a new videofile {file_path}')
        return file_path

    def get_label(self):
        return self.label

    def eos_callback(self, bus, msg):
        print(f'EOS in RTMP pipeline "{self.pipeline}"')
        self.launch_pipeline()
        return Gst.PadProbeReturn.OK

    def error_callback(self, bus, msg):
        element = msg.src
        element_name = element.get_property('name')
        parent = element.get_parent()
        if parent:
            parent_name = parent.get_property('name')
        else:
            parent_name = ''
        print(f'ERROR in main pipeline from {element_name}, parent = {parent_name}: {msg.parse_error()}')
        if parent in self.source_bins:
            print(f'!!!!!!!!!!!!!!!!!!!!!!Error in source bin, need to remove it. It will be launched back automatically by call back')
            if self.source_bins[0]:
                if parent.get_property('name') == self.source_bins[0].get_property('name'):
                    self.disconnect_usb_camera(0)
            if self.source_bins[1]:
                if parent.get_property('name') == self.source_bins[1].get_property('name'):
                    self.disconnect_usb_camera(1)

        else:
            print(f'Error in RTMP pipeline "{self.pipeline}":{msg.parse_error()}')
            if self.pipeline:
                print(f'Calling async pipeline destruction for output_connector class "{self.label}"')
                self.pipeline.call_async(remove_pipeline, self.label)
                time.sleep(5)
                print(f'End of calling async pipeline destruction for output_connector class "{self.label}"')

            exit(2)

        return Gst.PadProbeReturn.OK

    def state_changed_callback(self, bus, msg):
        old, new, pending = msg.parse_state_changed()
        if not msg.src == self.pipeline:
            # not from the pipeline, ignore
            return
        self.status = Gst.Element.state_get_name(new)
        print(f'RTMP pipeline "{self.label}" state changed from {Gst.Element.state_get_name(old)} to {Gst.Element.state_get_name(new)}')

    def on_stream_status(self, bus, msg):
        strct = msg.get_structure()
        print(f'STREAM_STATUS{strct.to_string()}')

    def on_request_state(self, bus, msg):
        strct = msg.get_structure()
        print(f'STREAM_STATUS{strct.to_string()}')

    def on_info(self, bus, msg):
        strct = msg.get_structure()
        if strct.has_name(f"rtmpsink{self.label}"):
            print("Element message detected")
            print(strct.to_string())
    def on_warning(self, bus, msg):
        strct = msg.get_structure()
        if strct.has_name(f"rtmpsink{self.label}"):
            print("Element message detected")
            print(strct.to_string())

    def run_pipeline(self):
        self.loop = GLib.MainLoop()

        self.pipeline.set_state(Gst.State.PLAYING)
        try:
            self.loop.run()
        except:
            sys.stderr.write("\n\n\n*** ERROR: main event loop exited!\n\n\n")
        finally:
            print('Running safe destruction of pipelines')
            if self.pipeline:
                self.__del__()
                del self.pipeline
            else:
                del self.pipeline
            print('Safe destruction of pipelines done')

    def __del__(self):
        print(f'Destructor of output connector "{self.label}" class')
        if self.source_bins[0]:
            self.disconnect_usb_camera(0)
        if self.source_bins[1]:
            self.disconnect_usb_camera(1)

        time.sleep(0.5)
        if self.pipeline:
            self.pipeline.send_event(Gst.Event.new_eos())
            time.sleep(0.1)

            self.pipeline.set_state(Gst.State.READY)
            self.pipeline.set_state(Gst.State.NULL)
            time.sleep(0.1)
            self.pipeline=None

def fetch_device_settings(serial):
    """Fetches device settings and configuration data from the integration endpoint."""
    try:
        response = requests.post(INTEGRATION_ENDPOINT, data={"serial": serial})
        response_data = response.json()

        # Retrieve global settings
        global_settings = {
            'is_reserve': response_data['data']['device']['isReserve'],
            'silence_audio': response_data['data']['device']['deviceSettings']['silenceAudio']
        }

        # Retrieve WiFi settings
        wifi_settings = response_data['data']['device']['wifiSettings']
        
        # Retrieve channels
        channels = response_data['data']['device'].get('channels', {})

        return global_settings, wifi_settings, channels

    except Exception as e:
        exc_tb = sys.exc_info()
        print(f"Error in '{exc_tb.tb_frame.f_code.co_filename}' at line {exc_tb.tb_lineno}: {e}")
        traceback.print_exc()
        return None, None, {}

def configure_streaming_endpoints(channels):
    """Configures streaming endpoints and settings for available cameras."""
    streaming_endpoints = {}
    camera_settings = {}

    # Helper functions to get streaming URL and settings
    def get_stream_url(channel):
        return channel['ingestEndpoint'] + channel['streamKey']

    def get_settings(channel):
        return {
            'bitrate': channel['bitrate'] * 1000,
            'white_balance': channel['whiteBalance']
        }

    # Set up endpoints and settings for each camera
    for cam in ['camera1', 'camera2']:
        if cam in channels:
            streaming_endpoints[cam] = get_stream_url(channels[cam])
            camera_settings[cam] = get_settings(channels[cam])

    return streaming_endpoints, camera_settings

def main(args):
    global device_slot, current_settings1, current_settings2
    global current_global_settings, current_wifi_settings, output, serial, CHECK_SETTINGS_EVERY, CHECK_FILES_EVERY
    
    serial = get_serial_number()
    
    configure_network_priorities()
    check_wifi_and_apply_changes()
    
    fetch_integration_values(serial)
    
    # Initialize GStreamer
    Gst.init(None)
    

    # Start periodic settings check thread
    threading.Thread(target=run_periodically, args=(CHECK_SETTINGS_EVERY,), daemon=True).start()

    # Main loop to wait for streaming readiness
    wait_for_streaming = True
    while wait_for_streaming:
        global_settings, wifi_settings, channels = fetch_device_settings(serial)

        # Break if fetching failed
        if global_settings is None:
            return 1

        # Configure streaming if channels are provided
        streaming_endpoints, camera_settings = configure_streaming_endpoints(channels)
        wait_for_streaming = global_settings['is_reserve'] or not bool(channels)
        
        if wait_for_streaming:
            print('Waiting for streaming...')
        else:
            print("Starting streaming process")
            print(f"Endpoints: {streaming_endpoints}")

        # Update global and WiFi settings
        current_global_settings = global_settings
        current_wifi_settings = wifi_settings
        current_settings1 = camera_settings.get('camera1')
        current_settings2 = camera_settings.get('camera2')

    # Configure and initialize GStreamer output
    device_slot = [VIDEO_DEVICE1, VIDEO_DEVICE2] if not AUTO_DETECT_USB_PORTS else []
    output = output_connector(
        label="stream_output",
        rtmp_path1=streaming_endpoints.get('camera1'),
        rtmp_path2=streaming_endpoints.get('camera2'),
        settings1=current_settings1,
        settings2=current_settings2,
        global_settings=current_global_settings
    )

    # Schedule periodic checks
    GLib.timeout_add_seconds(CHECK_USB_EVERY, cb_check_usb, output)
    GLib.timeout_add_seconds(CHECK_SETTINGS_EVERY, cb_check_settings, None)

    # Start GTK loop and GStreamer pipeline
    Gtk.main()
    output.run_pipeline()

if __name__ == '__main__':
    sys.exit(main(sys.argv))