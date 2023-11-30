#!/usr/bin/env python3
import os
from os import path, listdir, remove
from datetime import datetime
import time
import requests
import subprocess
import re
from dotenv import load_dotenv
from pyngrok import ngrok
import NetworkManager
from dbus import SystemBus, Interface
#from dbus.types import Dictionary, String, Array, ByteArray, Byte

interface_netman = "org.freedesktop.NetworkManager"
path_netman_settings = "/org/freedesktop/NetworkManager/Settings"

interface_settings = "org.freedesktop.NetworkManager.Settings"
interface_connection = "org.freedesktop.NetworkManager.Settings.Connection"

load_dotenv()

BITRATE = int(os.environ["BITRATE"])
OUTPUT_WATCHDOG_TIMEOUT = int(os.environ["OUTPUT_WATCHDOG_TIMEOUT"])
VIDEO_DURATION = int(os.environ["VIDEO_DURATION"])
VIDEO_FOLDER = os.environ["VIDEO_FOLDER"]
VIDEO_DEVICE1 = os.environ["VIDEO_DEVICE1"]
VIDEO_DEVICE2 = os.environ["VIDEO_DEVICE2"]
AUDIO_DEVICE = os.environ["AUDIO_DEVICE"]
VIDEO_FRAMERATE1 = int(os.environ["VIDEO_FRAMERATE1"])
VIDEO_FRAMERATE2 = int(os.environ["VIDEO_FRAMERATE2"])
VIDEO_KEEP_HOURS = int(os.environ["VIDEO_KEEP_HOURS"])
INTEGRATION_ENDPOINT = os.environ["INTEGRATION_ENDPOINT"]
INTEGRATION_ENDPOINT_UPDATE = os.environ["INTEGRATION_ENDPOINT_UPDATE"]
CHECK_FILES_EVERY = int(os.environ["CHECK_FILES_EVERY"])#seconds - check and remove old files
DO_LOCAL_OUTPUT = int(os.environ["DO_LOCAL_OUTPUT"])
LOCAL_ENDPOINT1 = os.environ["LOCAL_ENDPOINT1"]
LOCAL_ENDPOINT2 = os.environ["LOCAL_ENDPOINT2"]
AUTO_DETECT_USB_PORTS = int(os.environ["AUTO_DETECT_USB_PORTS"])
CHECK_USB_EVERY = int(os.environ["CHECK_USB_EVERY"])#seconds - check usb cameras
CHECK_SETTINGS_EVERY = int(os.environ["CHECK_SETTINGS_EVERY"])#seconds - check settings for cameras by API
SKIP_CAMERAS_VALUE = int(os.environ["SKIP_CAMERAS_VALUE"])
AUTO_DETECT_AUDIO = int(os.environ["AUTO_DETECT_AUDIO"])
SKIP_AUDIO_VALUE = int(os.environ["SKIP_AUDIO_VALUE"])

os.environ["GST_DEBUG"] = '2,flvmux:1'

import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst

l_devices = None
d_counter = None
current_settings1 = None
current_settings2 = None
current_global_settings = None
current_wifi_settings = None
output = None
serial = None
skip_audio_val=0
skip_cameras_val=0

def remove_old_files(folder, extension, hours_delta):
    now = datetime.now()
    files_to_by_extension = [path.join(folder, f) for f in listdir(folder) if
                             f.endswith(extension)]
    removed_files_counter = 0
    for f in files_to_by_extension:
        delta = now - datetime.fromtimestamp(path.getmtime(f))
        if delta.seconds//3600 > hours_delta:
            try:
                remove(f)
                print(f'File {f} was removed')
                removed_files_counter += 1
            except OSError:
                print(f'Error occured, file {f} was not removed')
                pass
    return removed_files_counter

def cb_timeout(b):
    try:
        print('Started removing old files job')
        num_removed=remove_old_files(current_global_settings['video_folder'], 'mp4', VIDEO_KEEP_HOURS)
        print(f'Finished removing old files job, total {num_removed} files was removed')
    except Exception as ex:
        print(f'Exception at callback {str(ex)}')
        return True
    return True


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
            print(f'Found device #{d_counter}: address {d_address} name {d_name}')
    #rejecting first several devices in system
    d_counter-=SKIP_CAMERAS_VALUE
    if d_counter > 2:
        print(f'More than 2 cameras found, we would use last 2')
    elif d_counter == 2:
        print(f'All 2 cameras found automatically')
    elif d_counter == 0:
        print('Unable to find cameras')
    elif d_counter == 1:
        print('Only 1 camera found')
    return l_devices, d_counter

def get_audio_devices():
    cmd_devices = """aplay -l | grep card"""
    devicesstr = subprocess.run(["bash", "-c", cmd_devices], stdout=subprocess.PIPE)
    devices = devicesstr.stdout.decode('utf-8')
    d_counter = 0
    l_devices = []
    for d in devices.split('\n'):
        if len(d) > 0:
            d_counter += 1
            d_name = ' '.join(d.split(':')[1:])
            d_address = f"hw:{d.split(':')[0].split(' ')[-1]},0"
            l_devices.append(d_address)
            print(f'Found device #{d_counter}: address {d_address} description {d_name}')
    #rejecting first several devices in system
    d_counter-=SKIP_AUDIO_VALUE
    if d_counter > 1:
        print(f'More than 1 audios found, we would use the last one')
    elif d_counter == 0:
        print('Unable to find audio input, would use silence instead')
    elif d_counter == 1:
        print('The only audio found')
    return l_devices, d_counter


def compare_usb_devices(l_devices, d_counter, l_devices_new, d_counter_new):
    if (d_counter != d_counter_new) or (len(l_devices) != len(l_devices_new)):
        print('Number of USB cameras changed')
        return False
    else:
        for i in range(len(l_devices)):
            if l_devices[i] != l_devices_new[i]:
                return False
    return True

def cb_check_usb(b):
    try:
        print('Callback: performing USB check')
        l_devices_new, d_counter_new = get_usb_devices()
        if not compare_usb_devices(l_devices, d_counter, l_devices_new, d_counter_new):
            print('Connected USB cameras configuration changed. Relaunching script')
            exit(3)
        else:
            pass
            #print('No changes of USB cameras observed')
    except Exception as ex:
        print(f'Exception at USB check callback: {str(ex)}')
        return True
    return True

def get_cameras_settings():
    try:
        req3 = requests.post(INTEGRATION_ENDPOINT, data={"serial": serial})
        print(f'Received: {req3}')
        req_data = req3.json()
        #print(f"ssh={req_data['data']['device']['enable_ssh']}")
        settings1 = {'bitrate': req_data['data']['channels'][0]['bitrate'] * 1000,
                     'white_balance': req_data['data']['channels'][0]['whiteBalance']}
        settings2 = {'bitrate': req_data['data']['channels'][1]['bitrate'] * 1000,
                     'white_balance': req_data['data']['channels'][1]['whiteBalance']}
        skip_audio_val_parameter = req_data['data']['device']['settings']['skip_audio_value']
        if skip_audio_val_parameter < 0:
            skip_audio_val_parameter = 0
        if 'skip_cameras_val' in req_data['data']['device']['settings'].keys():
            skip_cameras_val_parameter = req_data['data']['device']['settings']['skip_cameras_val']
        else:
            skip_cameras_val_parameter = SKIP_CAMERAS_VALUE
        if skip_cameras_val_parameter < 0:
            skip_cameras_val_parameter = 0
        global_settings = {'enable_ssh': req_data['data']['device']['enable_ssh'],
                           'ngrok_authtoken': req_data['data']['device']['ngrokId'],
                           'skip_audio_val': skip_audio_val_parameter,
                           'skip_cameras_val': skip_cameras_val_parameter,
                           'video_output': req_data['data']['device']['settings']['video_output'],
                           'is_reserve': req_data['data']['device']['is_reserve']}
        wifi_settings = req_data['data']['device']['wifi_settings']
        do_renew_wifi = req_data['data']['device']['doResetWifi']

    except:
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
            #print('No changes of settings observed')
        #print(set(current_global_settings.items()) ^ set(global_settings.items()))
        #print(set(current_global_settings.items()))
        #print(set(global_settings.items()))
        if len(set(current_global_settings.items()) ^ set(global_settings.items())) > 0:
            print('Device settings changed. Adjusting')
            output.modify_device_settings(global_settings)
            current_global_settings = global_settings
        else:
            pass
            # print('No changes of settings observed')
        if do_renew_wifi:
            print('Device wifi settings asked to be changed. Adjusting')
            output.modify_wifi_settings(wifi_settings)
            current_wifi_settings = wifi_settings
        else:
            pass
            # print('No changes of settings observed')
    except Exception as ex:
        print(f'Exception at settings check callback: {str(ex)}')
        return True
    return True


def remove_pipeline(pipeline, label):
    print(f'Pipeline "{label}" is removing')

    pipeline.send_event(Gst.Event.new_eos())
    time.sleep(0.1)

    state = pipeline.set_state(Gst.State.READY)
    # print(f'1******{state}')
    time.sleep(0.5)
    # print(f'!!!!!!!!!{self.pipeline.get_state(Gst.CLOCK_TIME_NONE)}')
    state = pipeline.set_state(Gst.State.NULL)
    #print(f'2******{state}')
    time.sleep(0.5)
    #print(f'!!!!!!!!!{pipeline.get_state(Gst.CLOCK_TIME_NONE)}')

    pipeline = None
    #self.bus = None
    time.sleep(0.5)
    print(f'Removed pipeline "{label}"')

def list_all_connections():
    bus = SystemBus()
    settings_proxy = bus.get_object(interface_netman, path_netman_settings)
    settings = Interface(settings_proxy, interface_settings)
    connections = settings.ListConnections()
    # connections = NetworkManager.Settings.ListConnections()
    for connection in connections:
        this_connection = bus.get_object(interface_netman, connection)
        this_connection_interface = Interface(this_connection, interface_connection)
        settings = this_connection_interface.GetSettings()
        connection_uuid = settings['connection']['uuid']
        connection_type = settings['connection']['type']
        #connection_type = settings['connection']['priority']
        print(f"Connection UUID: {connection_uuid}, Type: {connection_type}")
def set_networks_priorities(connection_type, priority):
    bus = SystemBus()
    settings_proxy = bus.get_object(interface_netman, path_netman_settings)
    settings = Interface(settings_proxy, interface_settings)
    connections = settings.ListConnections()
    # connections = NetworkManager.Settings.ListConnections()
    for connection in connections:
        this_connection = bus.get_object(interface_netman, connection)
        this_connection_interface = Interface(this_connection, interface_connection)
        settings = this_connection_interface.GetSettings()
        if settings['connection']['type'] == connection_type:
            connection.SetAutoconnectPriority(priority)


class NgrokTunnel():
    def __init__(self):
        self.is_ssh_launched = False
        self.ssh_tunnel = None

    def launch_ngrok(self, authtoken):
        print(f'Launching ngrok ssh tunnel')
        ngrok.set_auth_token(authtoken)
        self.ssh_tunnel = ngrok.connect("22", "tcp")
        l = self.ssh_tunnel.public_url[6:].split(':')
        self.is_ssh_launched = True
        self.ssh_address = f'ssh nifty@{l[0]} -p {l[1]}'
        req3 = requests.put(INTEGRATION_ENDPOINT_UPDATE, data={"serial": serial, "ssh_address": self.ssh_address})
        print(f'Received answer on PUT request: {req3}')
        print(f'Ngrok launched with ssh address: {self.ssh_address}')

    def get_current_ngrok_tunnel(self):
        if self.ssh_tunnel:
            l = self.ssh_tunnel.public_url[6:].split(':')
            return f'ssh nifty@{l[0]} -p {l[1]}'
        else:
            return ''

    def check_and_update_tunnel(self):
        new_address = self.get_current_ngrok_tunnel()
        if self.ssh_address != new_address:
            print('Updating ngrok tunnel address')
            req3 = requests.put(INTEGRATION_ENDPOINT_UPDATE, data={"serial": serial, "ssh_address":new_address})
            print(f'Received answer on PUT request: {req3}')
            self.ssh_address = new_address

    def interrupt_ngrok(self):
        print(f'Interrupting ngrok ssh tunnel')
        ngrok.kill()
        self.is_ssh_launched = False
        self.ssh_tunnel = None
        self.ssh_address = ''
        req3 = requests.put(INTEGRATION_ENDPOINT_UPDATE, data={"serial": serial, "ssh_address": 'Ssh tunnel not active'})
        print(f'Received answer on PUT request: {req3}')
        return 'Ssh tunnel not active'


class output_connector():
    def __init__(self, label, rtmp_path1, rtmp_path2, device1, device2, settings1, settings2, global_settings):
        print(f'Init output_connector "{label}" class')
        self.pipeline=None
        self.label=label
        self.save_path=global_settings['video_output']
        self.bitrate=BITRATE
        self.watchdog_timeout=OUTPUT_WATCHDOG_TIMEOUT
        self.rtmp_path1=rtmp_path1
        self.rtmp_path2=rtmp_path2
        self.video_duration=VIDEO_DURATION
        self.status='NULL'
        self.active_camera=None
        self.device1 = device1
        self.device2 = device2
        self.settings1 = settings1
        self.settings2 = settings2
        self.global_settings = global_settings
        self.ngrok_tunnel = NgrokTunnel()

        if self.device1 and self.device2:
            self.num_devices = 2
        elif self.device1 and self.device2 is None:
            self.num_devices = 1

        if AUTO_DETECT_AUDIO:
            l_audio_devices, d_audio_counter = get_audio_devices()
            if d_audio_counter >=1:
                self.with_audio = True
                self.audio_device = l_audio_devices[-1]
            else:
                self.with_audio = False
        else:
            if len(AUDIO_DEVICE) == 0:
                self.with_audio = False
            else:
                self.with_audio = True
                self.audio_device = AUDIO_DEVICE

        self.pipeline=None
        self.launch_pipeline()

    def launch_pipeline(self):
        if self.pipeline:
            print(f'Calling async pipeline destruction for output_connector class "{self.label}"')
            self.pipeline.call_async(remove_pipeline, self.label)
            time.sleep(5)
            print(f'End of calling async pipeline destruction for output_connector class "{self.label}"')

        rtmp_output_element = 'rtmpsink' if DO_LOCAL_OUTPUT else 'rtmp2sink'

        print(f'==================Creating a new pipeline=====================\n')
        if self.with_audio:
            audio_input = f'alsasrc device={self.audio_device} ! audioresample ! audio/x-raw,rate=48000 ! voaacenc bitrate=96000 ! audio/mpeg ! aacparse ! audio/mpeg, mpegversion=4'
        else:
            audio_input = f'audiotestsrc is-live=1 wave=silence ! audioresample ! audio/x-raw,rate=48000 ! voaacenc bitrate=96000 ! audio/mpeg ! aacparse ! audio/mpeg, mpegversion=4'

        if self.num_devices == 2:
            gcommand = f"""v4l2src do-timestamp=1 device={self.device1} ! image/jpeg,framerate={VIDEO_FRAMERATE1}/1,width=1920,height=1080 ! queue ! mppjpegdec ! videoconvert !  
                mpph264enc name=encoder1 profile=main qos=1 header-mode=1 profile=main bps={BITRATE} bps-max={BITRATE+1000000} rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee1_{self.label} ! 
                queue ! flvmux name=mux streamable=1 ! watchdog timeout={self.watchdog_timeout} ! {rtmp_output_element} sync=0 name=rtmpsink1{self.label} location=\"{self.rtmp_path1}\"
                v4l2src do-timestamp=1 device={self.device2} ! image/jpeg,framerate={VIDEO_FRAMERATE2}/1,width=1920,height=1080 ! queue ! mppjpegdec ! videoconvert !  
                mpph264enc name=encoder2 profile=main qos=1 header-mode=1 profile=main bps={BITRATE} bps-max={BITRATE+1000000} rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee2_{self.label} ! 
                queue ! flvmux name=mux2 streamable=1 ! watchdog timeout={self.watchdog_timeout} ! {rtmp_output_element} sync=0 name=rtmpsink2{self.label} location=\"{self.rtmp_path2}\"
                {audio_input} ! tee name=audiotee ! queue ! mux.
                audiotee. !  queue ! mux2. 
                tee1_{self.label}. ! queue !  
                splitmuxsink name=splitmuxsink1{self.label} async-handling=1 message-forward=1 max-size-time={self.video_duration * 60 * 1000000000} location={self.save_path}start1_{self.label}.mp4
                tee2_{self.label}. ! queue !  
                splitmuxsink name=splitmuxsink2{self.label} async-handling=1 message-forward=1 max-size-time={self.video_duration * 60 * 1000000000} location={self.save_path}start2_{self.label}.mp4"""
        elif self.num_devices == 1:
            gcommand = f"""v4l2src do-timestamp=1 device={self.device1} ! image/jpeg,framerate={VIDEO_FRAMERATE1}/1,width=1920,height=1080 ! queue ! mppjpegdec ! videoconvert !  
                mpph264enc name=encoder1 profile=main qos=1 header-mode=1 profile=main bps={BITRATE} bps-max={BITRATE+1000000} rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee1_{self.label} ! 
                queue ! flvmux name=mux streamable=1 ! watchdog timeout={self.watchdog_timeout} ! {rtmp_output_element} sync=0 name=rtmpsink1{self.label} location=\"{self.rtmp_path1}\"
                {audio_input} ! tee name=audiotee ! queue ! mux.
                tee1_{self.label}. ! queue !  
                splitmuxsink name=splitmuxsink1{self.label} async-handling=1 message-forward=1 max-size-time={self.video_duration * 60 * 1000000000} location={self.save_path}start1_{self.label}.mp4"""

        print(f'Gstreamer pipeline: {gcommand}\n')
        self.pipeline = Gst.parse_launch(gcommand)

        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()

        self.bus.connect('message::eos', self.eos_callback)
        self.bus.connect('message::error', self.error_callback)
        self.bus.connect('message::state-changed', self.state_changed_callback)
        self.bus.connect('message::info', self.on_info)
        self.bus.connect('message::warning', self.on_warning)
        self.bus.connect('message::stream_status', self.on_stream_status)
        self.bus.connect('message::request_state', self.on_request_state)

        sink = self.pipeline.get_by_name(f'splitmuxsink1{self.label}')
        sink.connect('format-location', self.format_location_callback1)
        if self.num_devices == 2:
            sink = self.pipeline.get_by_name(f'splitmuxsink2{self.label}')
            sink.connect('format-location', self.format_location_callback2)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.modify_settings(self.settings1, self.settings2)
        self.modify_device_settings(self.global_settings)

    def modify_settings(self, settings1, settings2):
        print(f'Using new settings for camera1: {settings1} and camera2: {settings2}')
        if self.device1:
            encoder1 = self.pipeline.get_by_name('encoder1')
            encoder1.set_property('bps', settings1['bitrate'])
            encoder1.set_property('bps-max', settings1['bitrate']+1000000)
            disable_auto_white_balance_cmd1 = f'v4l2-ctl --device {self.device1} -c white_balance_temperature_auto=0'
            disable_auto_white_balance1 = subprocess.run(["bash", "-c", disable_auto_white_balance_cmd1], stdout=subprocess.PIPE)
            set_white_balance_cmd1 = f'v4l2-ctl --device {self.device1} -c white_balance_temperature={settings1["white_balance"]}'
            set_white_balance1 = subprocess.run(["bash", "-c", set_white_balance_cmd1], stdout=subprocess.PIPE)
        self.settings1 = settings1
        if self.device2:
            encoder2 = self.pipeline.get_by_name('encoder2')
            encoder2.set_property('bps', settings2['bitrate'])
            encoder2.set_property('bps-max', settings2['bitrate']+1000000)
            disable_auto_white_balance_cmd2 = f'v4l2-ctl --device {self.device2} -c white_balance_temperature_auto=0'
            disable_auto_white_balance2 = subprocess.run(["bash", "-c", disable_auto_white_balance_cmd2], stdout=subprocess.PIPE)
            set_white_balance_cmd2 = f'v4l2-ctl --device {self.device2} -c white_balance_temperature={settings2["white_balance"]}'
            set_white_balance2 = subprocess.run(["bash", "-c", set_white_balance_cmd2], stdout=subprocess.PIPE)
        self.settings2 = settings2

    def modify_device_settings(self, global_settings):
        print(f'Using new global settings for device: {global_settings}')

        #Process enable_ssh:
        if global_settings['enable_ssh'] and not self.ngrok_tunnel.is_ssh_launched:
            self.ngrok_tunnel.launch_ngrok(global_settings['ngrok_authtoken'])
        elif not global_settings['enable_ssh'] and self.ngrok_tunnel.is_ssh_launched:
            self.ngrok_tunnel.interrupt_ngrok()

        #Process skip_audio_val:
        #Process skip_cameras_val:
        #Process video_output:
        if ((self.global_settings['skip_audio_val'] != current_global_settings['skip_audio_val']) or
           (self.global_settings['skip_cameras_val'] != current_global_settings['skip_cameras_val']) or
           (self.global_settings['video_output'] != current_global_settings['video_output'])):
            print('skip_audio_val or skip_cameras_val or video_output has been changed, relaunching to enable')
            exit(4)

        #Process is_reserve. When true, we don't need to stream anymore
        if global_settings['is_reserve']:
            print('is_reserved has been changed, relaunching to enable stand by mode')
            exit(5)

        self.global_settings = global_settings

    def modify_wifi_settings(self, wifi_settings):
        for w in wifi_settings:
            ssid, password = w['ssid'], w['password']
            cmd_wifi = f"""if nmcli connection show | grep -q "{ssid}"; then
                              sudo nmcli connection modify {ssid} wifi-sec.key-mgmt wpa-psk &&
                              sudo nmcli connection modify {ssid} wifi-sec.psk {password}
                           else
                              sudo nmcli connection add con-name {ssid} type wifi ssid {ssid}
                              sudo nmcli connection modify {ssid} wifi-sec.psk {password}
                           fi
                        """
            #sudo nmcli connection modify {ssid} wifi-sec.key-mgmt wpa-psk &&
            wifi_result = subprocess.run(["bash", "-c", cmd_wifi], stdout=subprocess.PIPE)
        req3 = requests.put(INTEGRATION_ENDPOINT_UPDATE, data={"serial": serial, "doResetWifi":False, "wifiSettingsUpdated":True})
        print(f'Received answer on wifi updated PUT request: {req3}')


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
        print(f'Error in RTMP pipeline "{self.pipeline}":{msg.parse_error()}')

        if self.pipeline:
            print(f'Calling async pipeline destruction for output_connector class "{self.label}"')
            self.pipeline.call_async(remove_pipeline, self.label)
            time.sleep(5)
            print(f'End of calling async pipeline destruction for output_connector class "{self.label}"')

        exit(2)
        # print('NeedReload=True')
        # self.launch_pipeline()
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
        #self.bus = self.pipeline.get_bus()
        #self.bus.add_signal_watch()
        # bus.connect("message", bus_call, loop)

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
        if self.pipeline:
            self.pipeline.send_event(Gst.Event.new_eos())
            time.sleep(1)

            self.pipeline.set_state(Gst.State.READY)
            self.pipeline.set_state(Gst.State.NULL)
            time.sleep(0.1)
            self.pipeline=None

def main(args):
    global l_devices, d_counter
    global current_settings1, current_settings2, current_global_settings, current_wifi_settings
    global output
    global serial


    cmd_cpuinfo = """cat /proc/cpuinfo | grep Serial"""
    cpuinfo = subprocess.run(["bash", "-c", cmd_cpuinfo], stdout=subprocess.PIPE)
    serial_raw = cpuinfo.stdout.decode('utf-8').split(' ')[-1]
    serial = re.sub(r"[\n\t\s]*", "", serial_raw)

    print(f'Cpu serial is {serial}')

    print('Configuring connection priorities for network connections discovered:')
    list_all_connections()
    set_networks_priorities('ethernet', 0)
    set_networks_priorities('wifi', 10)
    set_networks_priorities('gsm', 50)
    set_networks_priorities('cdma', 50)

    Gst.init(None)

    wait_for_streaming = True
    ngrok_tunnel = NgrokTunnel()
    while wait_for_streaming:
        if not DO_LOCAL_OUTPUT:
            try:
                req3 = requests.post(INTEGRATION_ENDPOINT, data={"serial": serial})
                print(f'Received: {req3}')
                req_data = req3.json()
                #print(f'Json received: {req_data}')
                if req_data['data']['channels'] == []:
                    channelsProvided = False
                else:
                    channelsProvided = True
                    endpoint1, key1, playbackUrl1 = req_data['data']['channels'][0]['ingestEndpoint'], req_data['data']['channels'][0]['streamKey'], req_data['data']['channels'][0]['playbackUrl']
                    endpoint2, key2, playbackUrl2 = req_data['data']['channels'][1]['ingestEndpoint'], req_data['data']['channels'][1]['streamKey'], req_data['data']['channels'][1]['playbackUrl']
                    streaming_address1 = endpoint1 + key1
                    streaming_address2 = endpoint2 + key2
                    settings1 = {'bitrate': req_data['data']['channels'][0]['bitrate']*1000, 'white_balance': req_data['data']['channels'][0]['whiteBalance']}
                    settings2 = {'bitrate': req_data['data']['channels'][1]['bitrate']*1000, 'white_balance': req_data['data']['channels'][1]['whiteBalance']}
                skip_audio_val_parameter = req_data['data']['device']['settings']['skip_audio_value']
                if skip_audio_val_parameter < 0:
                    skip_audio_val_parameter = 0
                if 'skip_cameras_val' in req_data['data']['device']['settings'].keys():
                    skip_cameras_val_parameter = req_data['data']['device']['settings']['skip_cameras_val']
                else:
                    skip_cameras_val_parameter = SKIP_CAMERAS_VALUE
                if skip_cameras_val_parameter < 0:
                    skip_cameras_val_parameter = 0
                global_settings = {'enable_ssh': req_data['data']['device']['enable_ssh'],
                                   'ngrok_authtoken': req_data['data']['device']['ngrokId'],
                                   'skip_audio_val': skip_audio_val_parameter,
                                   'skip_cameras_val': skip_cameras_val_parameter,
                                   'video_output': req_data['data']['device']['settings']['video_output'],
                                   'is_reserve': req_data['data']['device']['is_reserve']}
                wifi_settings = req_data['data']['device']['wifi_settings']

                if not ngrok_tunnel.is_ssh_launched and global_settings['enable_ssh']:
                    ngrok_tunnel.launch_ngrok(global_settings['ngrok_authtoken'])
                if ngrok_tunnel.is_ssh_launched and not global_settings['enable_ssh']:
                    ngrok_tunnel.interrupt_ngrok()

            except:
                print(f'Error occured during API call')
                return 1
        else:
            channelsProvided = True
            streaming_address1 = LOCAL_ENDPOINT1
            streaming_address2 = LOCAL_ENDPOINT2
            settings1 = {'bitrate': BITRATE, 'white_balance': 6500}
            settings2 = {'bitrate': BITRATE, 'white_balance': 6500}
            global_settings = {'enable_ssh': False,
                               'skip_audio_val': SKIP_AUDIO_VALUE,
                               'skip_cameras_val': SKIP_CAMERAS_VALUE,
                               'video_output': VIDEO_FOLDER,
                               'is_reserve': False}
        time.sleep(10)
        wait_for_streaming = global_settings['is_reserve'] or not channelsProvided

    print("We're asked to stream, launching it")

    if ngrok_tunnel.is_ssh_launched:
        ngrok_tunnel.interrupt_ngrok()

    print(f'Streaming to endpoints: {streaming_address1}, {streaming_address2}')
    print(f'Playback URL: {playbackUrl1}, {playbackUrl2}')

    current_settings1 = settings1
    current_settings2 = settings2
    current_global_settings = global_settings
    current_wifi_settings = wifi_settings

    l_devices, d_counter = get_usb_devices()

    if AUTO_DETECT_USB_PORTS and (d_counter >= 2):
        output=output_connector('output', streaming_address1, streaming_address2, l_devices[-2], l_devices[-1], current_settings1, current_settings2, current_global_settings)
    elif AUTO_DETECT_USB_PORTS and (d_counter >= 1):
        output = output_connector('output', streaming_address1, streaming_address2, l_devices[-1], None, current_settings1, current_settings2, current_global_settings)
    else:
        output=output_connector('output', streaming_address1, streaming_address2, VIDEO_DEVICE1, VIDEO_DEVICE2, current_settings1, current_settings2, current_global_settings)

    GLib.timeout_add_seconds(CHECK_FILES_EVERY, cb_timeout, None)
    GLib.timeout_add_seconds(CHECK_USB_EVERY, cb_check_usb, None)
    GLib.timeout_add_seconds(CHECK_SETTINGS_EVERY, cb_check_settings, None)

    output.run_pipeline()

if __name__ == '__main__':
    sys.exit(main(sys.argv))