#!/usr/bin/env python3
import os
from os import path, listdir, remove
from datetime import datetime
import time
from itertools import cycle
import requests
import subprocess
import re
from dotenv import load_dotenv

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
CHECK_FILES_EVERY = int(os.environ["CHECK_FILES_EVERY"])#seconds - check and remove old files
DO_LOCAL_OUTPUT = int(os.environ["DO_LOCAL_OUTPUT"])
LOCAL_ENDPOINT1 = os.environ["LOCAL_ENDPOINT1"]
LOCAL_ENDPOINT2 = os.environ["LOCAL_ENDPOINT2"]
AUTO_DETECT_USB_PORTS = int(os.environ["AUTO_DETECT_USB_PORTS"])
CHECK_USB_EVERY = int(os.environ["CHECK_USB_EVERY"])#seconds - check usb cameras

os.environ["GST_DEBUG"] = '2,flvmux:1'

import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst

l_devices = None
d_counter = None


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
        num_removed=remove_old_files(VIDEO_FOLDER, 'mp4', VIDEO_KEEP_HOURS)
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
    if d_counter > 2:
        print(f'More than 2 cameras found, we would use first 2')
    elif d_counter == 2:
        print(f'All 2 cameras found automatically')
    elif d_counter == 0:
        print('Unable to find cameras')
    elif d_counter == 1:
        print('Only 1 camera found')
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
        #print('Performing USB check')
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

class output_connector():
    def __init__(self, label, save_path, rtmp_path1, rtmp_path2, device1, device2):
        print(f'Init output_connector "{label}" class')
        self.pipeline=None
        self.label=label
        self.save_path=save_path
        self.bitrate=BITRATE
        self.watchdog_timeout=OUTPUT_WATCHDOG_TIMEOUT
        self.rtmp_path1=rtmp_path1
        self.rtmp_path2=rtmp_path2
        self.video_duration=VIDEO_DURATION
        self.status='NULL'
        self.active_camera=None
        self.device1 = device1
        self.device2 = device2

        if self.device1 and self.device2:
            self.num_devices = 2
        elif self.device1 and self.device2 is None:
            self.num_devices = 1

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
        if self.num_devices == 2:
            gcommand = f"""v4l2src do-timestamp=1 device={self.device1} ! image/jpeg,framerate={VIDEO_FRAMERATE1}/1,width=1920,height=1080 ! queue ! mppjpegdec ! videoconvert !  
                mpph264enc profile=main qos=1 header-mode=1 profile=main bps={BITRATE} bps-max={BITRATE+1000000} rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee1_{self.label} ! 
                queue ! flvmux name=mux streamable=1 ! watchdog timeout={self.watchdog_timeout} ! {rtmp_output_element} sync=0 name=rtmpsink1{self.label} location=\"{self.rtmp_path1}\"
                v4l2src do-timestamp=1 device={self.device2} ! image/jpeg,framerate={VIDEO_FRAMERATE2}/1,width=1920,height=1080 ! queue ! mppjpegdec ! videoconvert !  
                mpph264enc profile=main qos=1 header-mode=1 profile=main bps={BITRATE} bps-max={BITRATE+1000000} rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee2_{self.label} ! 
                queue ! flvmux name=mux2 streamable=1 ! watchdog timeout={self.watchdog_timeout} ! {rtmp_output_element} sync=0 name=rtmpsink2{self.label} location=\"{self.rtmp_path2}\"
                alsasrc device={AUDIO_DEVICE} ! audioresample ! audio/x-raw,rate=48000 ! voaacenc bitrate=96000 ! audio/mpeg ! aacparse ! audio/mpeg, mpegversion=4 ! tee name=audiotee ! queue ! mux.
                audiotee. !  queue ! mux2. 
                tee1_{self.label}. ! queue !  
                splitmuxsink name=splitmuxsink1{self.label} async-handling=1 message-forward=1 max-size-time={self.video_duration * 60 * 1000000000} location={self.save_path}start1_{self.label}.mp4
                tee2_{self.label}. ! queue !  
                splitmuxsink name=splitmuxsink2{self.label} async-handling=1 message-forward=1 max-size-time={self.video_duration * 60 * 1000000000} location={self.save_path}start2_{self.label}.mp4"""
        elif self.num_devices == 1:
            gcommand = f"""v4l2src do-timestamp=1 device={self.device1} ! image/jpeg,framerate={VIDEO_FRAMERATE1}/1,width=1920,height=1080 ! queue ! mppjpegdec ! videoconvert !  
                mpph264enc profile=main qos=1 header-mode=1 profile=main bps={BITRATE} bps-max={BITRATE+1000000} rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee1_{self.label} ! 
                queue ! flvmux name=mux streamable=1 ! watchdog timeout={self.watchdog_timeout} ! {rtmp_output_element} sync=0 name=rtmpsink1{self.label} location=\"{self.rtmp_path1}\"
                alsasrc device={AUDIO_DEVICE} ! audioresample ! audio/x-raw,rate=48000 ! voaacenc bitrate=96000 ! audio/mpeg ! aacparse ! audio/mpeg, mpegversion=4 ! tee name=audiotee ! queue ! mux.
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
        if self.active_camera:
            time.sleep(3)
            self.connect_to_source(cameras[self.active_camera])

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

    def connect_to_source(self, source):
        print(f'Connecting camera {source} to output "{self.label}"')
        #caps = source.get_caps()
        #print_caps(caps, source.get_label())
        self.active_camera=source


    def disconnect_from_source(self):
        self.active_camera = None

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
            self.disconnect_from_source()
            self.pipeline.send_event(Gst.Event.new_eos())
            time.sleep(1)

            self.pipeline.set_state(Gst.State.READY)
            self.pipeline.set_state(Gst.State.NULL)
            time.sleep(0.1)
            self.pipeline=None

def main(args):
    global l_devices, d_counter

    Gst.init(None)

    cmd_cpuinfo = """cat /proc/cpuinfo | grep Serial"""
    cpuinfo = subprocess.run(["bash", "-c", cmd_cpuinfo], stdout=subprocess.PIPE)
    serial_raw = cpuinfo.stdout.decode('utf-8').split(' ')[-1]
    serial = re.sub(r"[\n\t\s]*", "", serial_raw)

    print(f'Cpu serial is {serial}')

    l_devices, d_counter = get_usb_devices()

    data = {
        "serial": serial
    }
    url = INTEGRATION_ENDPOINT

    if not DO_LOCAL_OUTPUT:
        try:
            req3 = requests.post(url, data=data)

            print(f'Received: {req3}')
            req_data = req3.json()
            print(f'Json received: {req_data}')
            endpoint1, key1, playbackUrl1 = req_data['data']['channels'][0]['ingestEndpoint'], req_data['data']['channels'][0]['streamKey'], req_data['data']['channels'][0]['playbackUrl']
            endpoint2, key2, playbackUrl2 = req_data['data']['channels'][1]['ingestEndpoint'], req_data['data']['channels'][1]['streamKey'], req_data['data']['channels'][1]['playbackUrl']
            streaming_address1 = endpoint1 + key1
            streaming_address2 = endpoint2 + key2
            print(f'Streaming to endpoints: {streaming_address1}, {streaming_address2}')
            print(f'Playback URL: {playbackUrl1}, {playbackUrl2}')
        except:
            print(f'Error occured during API call')
            return 1
    else:
        streaming_address1 = LOCAL_ENDPOINT1
        streaming_address2 = LOCAL_ENDPOINT2
        print(f'Streaming to endpoints: {streaming_address1}, {streaming_address2}')

    if AUTO_DETECT_USB_PORTS and (d_counter >= 2):
        output=output_connector('output', VIDEO_FOLDER, streaming_address1, streaming_address2, l_devices[0], l_devices[1])
    elif AUTO_DETECT_USB_PORTS and (d_counter >= 1):
        output = output_connector('output', VIDEO_FOLDER, streaming_address1, streaming_address2, l_devices[0], None)
    else:
        output=output_connector('output', VIDEO_FOLDER, streaming_address1, streaming_address2, VIDEO_DEVICE1, VIDEO_DEVICE2)

    GLib.timeout_add_seconds(CHECK_FILES_EVERY, cb_timeout, None)
    GLib.timeout_add_seconds(CHECK_USB_EVERY, cb_check_usb, None)

    output.run_pipeline()

if __name__ == '__main__':
    sys.exit(main(sys.argv))