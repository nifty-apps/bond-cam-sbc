#!/usr/bin/env python3
import os
from os import path, listdir, remove
from datetime import datetime
import time
from itertools import cycle
import requests

from dotenv import load_dotenv

load_dotenv()

OUTPUT_WIDTH = int(os.environ["OUTPUT_WIDTH"])
OUTPUT_HEIGHT = int(os.environ["OUTPUT_HEIGHT"])
STREAMING_ADDRESS = os.environ["STREAMING_ADDRESS"]
SWITCH_TIME = int(os.environ["SWITCH_TIME"])
BITRATE = int(os.environ["BITRATE"])
OUTPUT_WATCHDOG_TIMEOUT = int(os.environ["OUTPUT_WATCHDOG_TIMEOUT"])
VIDEO_DURATION = int(os.environ["VIDEO_DURATION"])
VIDEO_FOLDER = os.environ["VIDEO_FOLDER"]
VIDEO_KEEP_DAYS = int(os.environ["VIDEO_KEEP_DAYS"])
CHECK_FILES_EVERY = int(os.environ["CHECK_FILES_EVERY"])#seconds - check and remove old files
CAMERAS_CONFIG_FILENAME = os.environ["CAMERAS_CONFIG_FILENAME"]

data = {
    "serial": "eacfab1dec54898c"
}
token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiI2NTJkM2JiOWY1OTQ0ODViYzI0YjY4MDMiLCJlbWFpbCI6ImhhbnNyYWpyYW5hQGdtYWlsLmNvbSIsImlhdCI6MTY5NzUzNDUwMH0.E0-EF84ibZF4H5zci_5qH4VqkNQVPoSW1tBBaFvxzyI'
headers =  {"Content-Type":"raw/json", "Authorization": f"bearer {token}"}
url = "https://bond.niftyitsolution.com/bond-cam-backend/api/device/configure"


os.environ["GST_DEBUG"] = '2,flvmux:1'

import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst
from configparser import ConfigParser

def remove_old_files(folder, extension, days_delta):
    now = datetime.now()
    files_to_by_extension = [path.join(folder, f) for f in listdir(folder) if
                             f.endswith(extension)]
    removed_files_counter = 0
    for f in files_to_by_extension:
        delta = now - datetime.fromtimestamp(path.getmtime(f))
        if delta.days > days_delta:
            try:
                remove(f)
                print(f'File {f} was removed')
                removed_files_counter += 1
            except OSError:
                print(f'Error occured, file {f} was not removed')
                pass
    return removed_files_counter


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
    def __init__(self, label, save_path, rtmp_path):
        print(f'Init output_connector "{label}" class')
        self.pipeline=None
        self.label=label
        self.save_path=save_path
        self.bitrate=BITRATE
        self.watchdog_timeout=OUTPUT_WATCHDOG_TIMEOUT
        self.rtmp_path=rtmp_path
        self.video_duration=VIDEO_DURATION
        self.status='NULL'
        self.active_camera=None

        self.pipeline=None
        self.launch_pipeline()

    def launch_pipeline(self):
        if self.pipeline:
            print(f'Calling async pipeline destruction for output_connector class "{self.label}"')
            self.pipeline.call_async(remove_pipeline, self.label)
            time.sleep(5)
            print(f'End of calling async pipeline destruction for output_connector class "{self.label}"')

        gcommand = f"""v4l2src do-timestamp=1 device=/dev/video0 ! image/jpeg,framerate=30/1,width=1920,height=1080 ! queue ! mppjpegdec ! videoconvert !  
            mpph264enc profile=main qos=1 header-mode=1 profile=main bps=2000000 bps-max=4000000 rc-mode=vbr ! video/x-h264,level=(string)4 ! h264parse config-interval=1 ! tee name=tee_{self.label} ! 
            queue ! flvmux name=mux streamable=1 ! watchdog timeout=20000 ! rtmp2sink sync=0 name=rtmpsink{self.label} location=\"{self.rtmp_path}\"
            tee_{self.label}. ! queue ! 
            splitmuxsink name=splitmuxsink{self.label} async-handling=1 message-forward=1 max-size-time={self.video_duration * 60 * 1000000000} location={self.save_path}start_{self.label}.mp4"""
        #print(gcommand)
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

        sink = self.pipeline.get_by_name(f'splitmuxsink{self.label}')
        sink.connect('format-location', self.format_location_callback)
        self.pipeline.set_state(Gst.State.PLAYING)
        if self.active_camera:
            time.sleep(3)
            self.connect_to_source(cameras[self.active_camera])

    def format_location_callback(self, splitmux, fragment_id):
        now = datetime.now()
        file_path=f'{self.save_path}{now.isoformat()}.mp4'
        print(f'Output connector "{self.label}" is starting to record into a new videofile {file_path}')
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

        print('NeedReload=True')
        self.launch_pipeline()
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

    Gst.init(None)

    req3 = requests.post(url, data=data, headers=headers)

    req_data = req3.json()
    endpoint1, key1, playbackUrl1 = req_data['data']['channels'][0]['ingestEndpoint'], req_data['data']['channels'][0]['streamKey'], req_data['data']['channels'][0]['playbackUrl']
    # endpoint2, key2, playbackUrl2 = req_data['data']['channels'][1]['ingestEndpoint'], req_data['data']['channels'][1]['streamKey'], req_data['data']['channels'][1]['playbackUrl']
    streaming_address1 = endpoint1 + key1
    streaming_address1 = 'rtmps://3d226343218c.global-contribute.live-video.net:443/app/sk_ap-south-1_YROv9RFnY8KA_YI6qF0Go0sLwqlQlPz4OnpZa1L2abf'
    playbackUrl1 = 'https://3d226343218c.ap-south-1.playback.live-video.net/api/video/v1/ap-south-1.301233104418.channel.WqfQpbma5FQY.m3u8'
    print(f'Streaming to endpoint: {streaming_address1}')
    print(f'Playback URL: {playbackUrl1}')
    output1=output_connector('output1', VIDEO_FOLDER, streaming_address1)
    output1.run_pipeline()

if __name__ == '__main__':
    sys.exit(main(sys.argv))