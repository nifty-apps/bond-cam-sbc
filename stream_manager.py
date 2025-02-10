import gi
gi.require_version('Gst', '1.0')

import sys
import copy
from gi.repository import Gst, GLib
from logger import get_logger

logger = get_logger()

class StreamManager:
    def __init__(self, label, get_stream_settings):
        self.label = label
        self.get_stream_settings = get_stream_settings  # Callable to get current stream_settings
        self.stream_settings = {}  # Initialize stream_settings
        self.pipeline = None
        self.watchdog_timeout = 5000  # Set your desired watchdog timeout in milliseconds

        # Store current configuration
        self.current_video_streams = []
        self.audio_device = None
        self.current_audio_device = None  # Added to track the current audio device

        # Stores compositors for each camera to switch pads
        self.compositors = []

        # Tracks whether each camera is connected
        self.camera_connected = []

        # Stores the elements of each camera pipeline for easy removal
        self.camera_elements = []

        # Stores the requested sink pads for camera sources
        self.camera_sink_pads = []

        # Stores RTMP sink elements
        self.rtmp_sink_elements = []

        # Stores the v4l2src elements for dynamic property adjustments
        self.v4l2src_elements = []

        self.launch_pipeline()

    def launch_pipeline(self):
        # Initialize GStreamer
        Gst.init(None)

        # Fetch initial configuration
        self.fetch_stream_settings()

        # Create initial pipeline with placeholders
        self.build_pipeline()

        # Start periodic configuration check
        GLib.timeout_add_seconds(5, self.check_stream_info)

        # Start periodic camera device check
        GLib.timeout_add_seconds(5, self.check_camera_devices)

    def fetch_stream_settings(self):
        # Use the get_stream_settings function provided to get the latest settings
        self.stream_settings = self.get_stream_settings()

        # Handle case where get_stream_settings may return None or empty dict
        if not self.stream_settings:
            self.stream_settings = {}

        self.is_enabled = self.stream_settings.get('isEnabled', False)
        self.desired_video_streams = self.stream_settings.get('videoStreams', [])
        self.audio_device = self.stream_settings.get('audioDevice', None)

    def build_pipeline(self):
        # Check if streaming is enabled before building the pipeline
        if not self.is_enabled:
            logger.info('Streaming is disabled')
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
                self.pipeline = None
            return

        if self.pipeline:
            logger.info(f'Destroying existing pipeline for StreamManager "{self.label}"')
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        # Reset all stored information
        self.compositors = []
        self.camera_connected = []
        self.camera_elements = []
        self.camera_sink_pads = []
        self.rtmp_sink_elements = []
        self.v4l2src_elements = []

        # Build the pipeline
        gcommand = ""

        num_streams = len(self.desired_video_streams)
        if num_streams == 0:
            logger.info("No video streams defined in stream settings.")
            self.current_video_streams = []
            return

        for idx, stream in enumerate(self.desired_video_streams):
            camera_num = idx + 1
            channel = stream['channel']

            # User provides bitrate in Kbps; convert to bps
            bitrate_kbps = channel.get('bitrate', 2000)  # default 2000 Kbps
            bitrate = bitrate_kbps * 1000  # Convert Kbps to bps
            resolution = channel.get('resolution', {'width': 1920, 'height': 1080})
            width = resolution.get('width', 1920)
            height = resolution.get('height', 1080)
            rtmp_url = channel.get('streamEndpoint', '')  # Updated from rtmp_url to streamEndpoint

            # Create the fallback videotestsrc pipeline
            gcommand += f"""
                videotestsrc pattern=0 is-live=1 name=videotestsrc{camera_num} ! videoconvert ! video/x-raw,width={width},height={height} ! source_compositor{camera_num}.sink_0
                input-selector name=source_compositor{camera_num} sync-mode=1 ! videoconvert ! video/x-raw,format=NV12 !
                mpph264enc name=encoder{camera_num} profile=main qos=1 header-mode=1 bps={bitrate} bps-max={bitrate + 1000000} rc-mode=vbr ! h264parse config-interval=1 ! queue ! flvmux name=mux{camera_num} streamable=1 ! rtmp2sink sync=0 name=rtmpsink{camera_num}{self.label} location="{rtmp_url}"
            """

        # Setup audio pipeline
        if self.audio_device:
            audio_input = f'alsasrc device={self.audio_device} ! audioresample ! audio/x-raw,rate=48000 ! voaacenc bitrate=96000 ! aacparse ! audio/mpeg, mpegversion=4 '
        else:
            audio_input = f'audiotestsrc is-live=1 wave=silence ! audioresample ! audio/x-raw,rate=48000 ! voaacenc bitrate=96000 ! aacparse ! audio/mpeg, mpegversion=4 '

        # Link audio to mux elements based on the number of streams
        if num_streams == 1:
            gcommand += f"{audio_input} ! queue ! mux1.audio"
        elif num_streams > 1:
            gcommand += f"{audio_input} ! tee name=audiotee "
            for idx in range(num_streams):
                camera_num = idx + 1
                gcommand += f"audiotee. ! queue ! mux{camera_num}.audio "
        else:
            logger.info("No video streams defined in stream settings.")
            self.current_video_streams = []
            return

        logger.info(f'GStreamer pipeline:\n{gcommand}\n')

        # Create and set up the pipeline
        try:
            self.pipeline = Gst.parse_launch(gcommand)
        except Exception as e:
            logger.error(f"Failed to create pipeline: {e}")
            return

        # Get the bus to handle messages
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self.on_bus_message)

        # Set the input-selector to initially use the videotestsrc
        for idx in range(num_streams):
            self.camera_connected.append(False)
            self.camera_elements.append(None)
            self.camera_sink_pads.append(None)
            self.v4l2src_elements.append(None)

            camera_num = idx + 1
            compositor = self.pipeline.get_by_name(f'source_compositor{camera_num}')
            self.compositors.append(compositor)

            # Set to use the fallback (videotestsrc)
            sink_pad = compositor.get_static_pad('sink_0')
            if sink_pad:
                compositor.set_property("active-pad", sink_pad)
            else:
                logger.warning(f"Warning: Could not find sink_0 pad on source_compositor{camera_num}")

            # Store RTMP sink element for dynamic updates
            rtmp_sink = self.pipeline.get_by_name(f'rtmpsink{camera_num}{self.label}')
            self.rtmp_sink_elements.append(rtmp_sink)

        self.pipeline.set_state(Gst.State.PLAYING)

        # Copy current configuration
        self.current_video_streams = copy.deepcopy(self.desired_video_streams)
        self.current_audio_device = self.audio_device  # Update current audio device

    def check_stream_info(self):
        # Store previous enabled state
        was_enabled = self.is_enabled
        # Store previous audio device
        prev_audio_device = self.current_audio_device
        
        # Fetch new configuration
        self.fetch_stream_settings()
        
        # Handle enable/disable state changes
        if was_enabled != self.is_enabled:
            logger.info(f'Stream status changed to {"enabled" if self.is_enabled else "disabled"}')
            if self.is_enabled:
                logger.info(f'Starting stream')
                self.build_pipeline()
            else:
                logger.info(f'Stopping stream')
                if self.pipeline:
                    self.pipeline.set_state(Gst.State.NULL)
                    self.pipeline = None
            return True

        # Only check for other changes if streaming is enabled
        if not self.is_enabled:
            return True

        changes_require_rebuild = False

        # Check if the audio device has changed
        if prev_audio_device != self.audio_device:
            logger.info(f"Audio device changed from {prev_audio_device} to {self.audio_device}. Rebuilding pipeline.")
            changes_require_rebuild = True

        # Check if the number of streams has changed
        if len(self.desired_video_streams) != len(self.current_video_streams):
            logger.info("Number of video streams has changed.")
            changes_require_rebuild = True
        else:
            # Loop through each stream
            for idx, stream in enumerate(self.desired_video_streams):
                current_stream = self.current_video_streams[idx]
                # Compare RTMP URLs (streamEndpoint)
                desired_rtmp_url = stream['channel'].get('streamEndpoint', '')
                current_rtmp_url = current_stream['channel'].get('streamEndpoint', '')
                if desired_rtmp_url != current_rtmp_url:
                    logger.info(f"RTMP URL for stream {idx+1} has changed. Rebuilding pipeline.")
                    changes_require_rebuild = True
                    break
                # Compare camera paths
                desired_camera = stream['camera']
                current_camera = current_stream['camera']
                if desired_camera != current_camera:
                    logger.info(f"Camera for stream {idx+1} has changed. Rebuilding pipeline.")
                    changes_require_rebuild = True
                    break
                # Compare resolution
                desired_resolution = stream['channel'].get('resolution', {})
                current_resolution = current_stream['channel'].get('resolution', {})
                if desired_resolution != current_resolution:
                    logger.info(f"Resolution for stream {idx+1} has changed. Rebuilding pipeline.")
                    changes_require_rebuild = True
                    break
                # Compare framerate
                desired_framerate = stream['channel'].get('frameRate')  # Updated from framerate to frameRate
                current_framerate = current_stream['channel'].get('frameRate')  # Updated from framerate to frameRate
                if desired_framerate != current_framerate:
                    logger.info(f"Framerate for stream {idx+1} has changed. Rebuilding pipeline.")
                    changes_require_rebuild = True
                    break

        if changes_require_rebuild:
            logger.info("Rebuilding pipeline with new configuration.")
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
            self.build_pipeline()
        else:
            # Update RTMP URLs dynamically
            for idx, stream in enumerate(self.desired_video_streams):
                current_stream = self.current_video_streams[idx]
                new_rtmp_url = stream['channel'].get('streamEndpoint', '')  # Updated from rtmp_url to streamEndpoint
                old_rtmp_url = current_stream['channel'].get('streamEndpoint', '')  # Updated from rtmp_url to streamEndpoint
                if new_rtmp_url != old_rtmp_url:
                    logger.info(f"Updating RTMP URL for stream {idx+1}.")
                    rtmp_sink = self.rtmp_sink_elements[idx]
                    if rtmp_sink:
                        rtmp_sink.set_property('location', new_rtmp_url)
                    self.current_video_streams[idx]['channel']['streamEndpoint'] = new_rtmp_url  # Updated from rtmp_url to streamEndpoint

            # Update camera settings dynamically if possible
            for idx, stream in enumerate(self.desired_video_streams):
                current_stream = self.current_video_streams[idx]
                # Determine which settings have changed
                changed_settings = {}
                # Check for bitrate change
                if stream['channel'].get('bitrate') != current_stream['channel'].get('bitrate'):
                    changed_settings['bitrate'] = stream['channel'].get('bitrate')
                # Check for white balance change
                if stream['channel'].get('whiteBalance') != current_stream['channel'].get('whiteBalance'):  # Updated from white_balance to whiteBalance
                    changed_settings['whiteBalance'] = stream['channel'].get('whiteBalance')  # Updated from white_balance to whiteBalance

                if changed_settings:
                    logger.info(f"Updating channel settings for stream {idx+1}.")
                    self.update_camera_settings(idx, stream['channel'], changed_settings)
                    # Update only the dynamic settings in current_video_streams
                    for key in changed_settings:
                        current_stream['channel'][key] = stream['channel'].get(key)

        return True  # Continue calling this function periodically

    def update_camera_settings(self, idx, channel_settings, changed_settings):
        camera_num = idx + 1
        # Update encoder settings
        encoder = self.pipeline.get_by_name(f'encoder{camera_num}')
        if encoder and 'bitrate' in changed_settings:
            # User provides bitrate in Kbps; convert to bps
            bitrate_kbps = channel_settings.get('bitrate', 2000)  # default 2000 Kbps
            bitrate = bitrate_kbps * 1000  # Convert Kbps to bps
            encoder.set_property('bps', bitrate)
            encoder.set_property('bps-max', bitrate + 1000000)
            logger.info(f"Set bitrate to {bitrate_kbps} Kbps for stream {camera_num}")

        # Update white balance directly on v4l2src
        if self.camera_connected[idx] and 'whiteBalance' in changed_settings:  # Updated from white_balance to whiteBalance
            v4l2src = self.v4l2src_elements[idx]
            if v4l2src:
                white_balance = channel_settings.get('whiteBalance', 5000)  # Updated from white_balance to whiteBalance
                structure = Gst.Structure.new_empty("extra_controls")
                structure.set_value("white_balance_temperature_auto", 0)
                structure.set_value("white_balance_temperature", white_balance)
                v4l2src.set_property('extra-controls', structure)
                logger.info(f"Set white balance to {white_balance} for stream {camera_num}")

    def check_camera_devices(self):
        # Only check camera devices if streaming is enabled
        if not self.is_enabled:
            return True
        
        for idx, stream in enumerate(self.desired_video_streams):
            camera_address = stream['camera']
            # If camera address is None or invalid, remove any existing camera pipeline and switch to videotestsrc
            if self.camera_needs_update(idx, camera_address):
                if self.camera_connected[idx]:
                    logger.info(f"Camera {idx+1} is not available or address is None. Switching to videotestsrc.")
                    self.switch_to_videotestsrc(idx)
                    self.camera_connected[idx] = False
                    self.remove_camera_pipeline(idx)
            elif camera_address is not None and not self.camera_connected[idx]:
                # Attempt to connect to the camera
                logger.info(f"Attempting to connect to camera {idx+1} at {camera_address}")
                self.try_connect_camera(idx)
        return True  # Continue calling this function periodically

    def camera_needs_update(self, idx, camera_address):
        # Return True if the camera is not connected or the address is invalid
        if camera_address is None:
            return True
        return False

    def on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"ERROR: {err}, {debug}")
            src = message.src
            # Handle errors from v4l2src elements
            if src.get_name().startswith('v4l2src'):
                camera_num = int(src.get_name().replace('v4l2src', ''))
                idx = camera_num - 1
                logger.info(f"Camera {camera_num} error detected. Switching to videotestsrc.")
                self.switch_to_videotestsrc(idx)
                self.camera_connected[idx] = False
                # Remove the camera pipeline elements
                self.remove_camera_pipeline(idx)
                # Continue running
                return True
            # Handle errors from RTMP sinks
            if src.get_name().startswith('rtmpsink'):
                self.handle_rtmp_error(src)
                return True
            else:
                # Other errors, just log them
                logger.error(f"Error from element {src.get_name()}: {err}, {debug}")
                return True
        elif t == Gst.MessageType.EOS:
            src = message.src
            if src.get_name().startswith('v4l2src'):
                camera_num = int(src.get_name().replace('v4l2src', ''))
                idx = camera_num - 1
                logger.info(f"Camera {camera_num} EOS detected. Switching to videotestsrc.")
                self.switch_to_videotestsrc(idx)
                self.camera_connected[idx] = False
                # Remove the camera pipeline elements
                self.remove_camera_pipeline(idx)
        return True

    def switch_to_videotestsrc(self, idx):
        compositor = self.compositors[idx]
        sink_pad = compositor.get_static_pad('sink_0')  # videotestsrc pad
        compositor.set_property("active-pad", sink_pad)
        logger.info(f"Switched compositor {idx+1} to videotestsrc.")
        # Release the requested pad
        if self.camera_sink_pads[idx]:
            compositor.release_request_pad(self.camera_sink_pads[idx])
            self.camera_sink_pads[idx] = None

    def switch_to_camera(self, idx):
        compositor = self.compositors[idx]
        sink_pad = self.camera_sink_pads[idx]
        if sink_pad:
            compositor.set_property("active-pad", sink_pad)
            logger.info(f"Switched compositor {idx+1} to camera feed.")

    def try_connect_camera(self, idx):
        camera_num = idx + 1
        stream = self.desired_video_streams[idx]
        camera_address = stream['camera']

        # If camera_address is None, do not attempt to connect
        if camera_address is None:
            logger.info(f"Camera {camera_num} address is None. Skipping connection attempt.")
            return False

        # Remove any existing camera pipeline elements
        self.remove_camera_pipeline(idx)

        # Recreate the v4l2src element
        logger.info(f"Attempting to connect camera {camera_num} at {camera_address}")
        camera_source = Gst.ElementFactory.make('v4l2src', f'v4l2src{camera_num}')
        if not camera_source:
            logger.error(f"Failed to create v4l2src element for camera {camera_num}")
            return False

        camera_source.set_property('device', camera_address)

        # Test if the device can be set to READY state
        try:
            camera_source.set_state(Gst.State.READY)
            state_change_return, state, pending = camera_source.get_state(Gst.CLOCK_TIME_NONE)
            if state_change_return == Gst.StateChangeReturn.FAILURE:
                logger.error(f"Device {camera_address} cannot be set to READY state. It may not be a valid video capture device.")
                camera_source.set_state(Gst.State.NULL)
                return False
            # Set to NULL state before adding to pipeline
            camera_source.set_state(Gst.State.NULL)
        except Exception as e:
            logger.error(f"Exception while setting up v4l2src for camera {camera_num}: {e}")
            camera_source.set_state(Gst.State.NULL)
            return False

        # Proceed with adding elements to pipeline
        # Set initial white balance using extra-controls as Gst.Structure
        channel = stream['channel']
        white_balance = channel.get('white_balance', 5000)
        structure = Gst.Structure.new_empty("extra_controls")
        structure.set_value("white_balance_temperature_auto", 0)
        structure.set_value("white_balance_temperature", white_balance)
        camera_source.set_property('extra-controls', structure)

        # Build the rest of the camera pipeline
        bitrate_kbps = channel.get('bitrate', 2000)  # default 2000 Kbps
        bitrate = bitrate_kbps * 1000  # Convert Kbps to bps
        resolution = channel.get('resolution', {'width': 1920, 'height': 1080})
        width = resolution.get('width', 1920)
        height = resolution.get('height', 1080)
        framerate = channel.get('framerate', 30)

        # Set caps filter
        caps = Gst.Caps.from_string(f"image/jpeg, framerate={framerate}/1, width={width}, height={height}")
        caps_filter = Gst.ElementFactory.make('capsfilter', None)
        caps_filter.set_property('caps', caps)

        # Build the rest of the pipeline
        jpegdec = Gst.ElementFactory.make('jpegdec', None)
        videoconvert = Gst.ElementFactory.make('videoconvert', None)
        videoscale = Gst.ElementFactory.make('videoscale', None)
        scale_caps = Gst.Caps.from_string(f"video/x-raw,width={width},height={height}")
        scale_caps_filter = Gst.ElementFactory.make('capsfilter', None)
        scale_caps_filter.set_property('caps', scale_caps)
        queue = Gst.ElementFactory.make('queue', None)

        # Add elements to the pipeline
        elements = [camera_source, caps_filter, jpegdec, videoconvert, videoscale, scale_caps_filter, queue]
        for elem in elements:
            if not elem:
                logger.error(f"Failed to create one of the elements in camera {camera_num} pipeline.")
                # Clean up
                for e in elements:
                    if e:
                        e.set_state(Gst.State.NULL)
                        self.pipeline.remove(e)
                return False
            self.pipeline.add(elem)

        # Link elements
        if not self.link_elements(elements):
            logger.error(f"Failed to link camera {camera_num} elements.")
            for elem in elements:
                elem.set_state(Gst.State.NULL)
                self.pipeline.remove(elem)
            return False

        # Request a new sink pad from the compositor
        compositor = self.compositors[idx]
        sink_pad = compositor.get_request_pad('sink_%u')
        if not sink_pad:
            logger.error(f"Failed to get request pad for camera {camera_num}")
            for elem in elements:
                elem.set_state(Gst.State.NULL)
                self.pipeline.remove(elem)
            return False

        # Store the sink pad for future reference
        self.camera_sink_pads[idx] = sink_pad

        # Get the source pad of the last element
        src_pad = queue.get_static_pad('src')
        if not src_pad.link(sink_pad) == Gst.PadLinkReturn.OK:
            logger.error(f"Failed to link camera {camera_num} to compositor.")
            compositor.release_request_pad(sink_pad)
            self.camera_sink_pads[idx] = None
            for elem in elements:
                elem.set_state(Gst.State.NULL)
                self.pipeline.remove(elem)
            return False

        # Set the camera source and its elements to PLAYING
        ret = camera_source.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error(f"Failed to set camera {camera_num} to PLAYING state.")
            # Clean up
            for elem in elements:
                elem.set_state(Gst.State.NULL)
                self.pipeline.remove(elem)
            self.camera_sink_pads[idx] = None
            compositor.release_request_pad(sink_pad)
            return False

        for elem in elements[1:]:
            elem.sync_state_with_parent()

        # Store the elements and the v4l2src element for adjustments
        self.camera_elements[idx] = elements
        self.v4l2src_elements[idx] = camera_source

        # Switch to camera feed
        self.switch_to_camera(idx)

        # Mark the camera as connected
        self.camera_connected[idx] = True

        logger.info(f"Successfully connected camera {camera_num}.")

        return False  # Stop trying to connect this camera for now

    def link_elements(self, elements):
        for i in range(len(elements) - 1):
            if not elements[i].link(elements[i + 1]):
                logger.error(f"Failed to link {elements[i].get_name()} to {elements[i + 1].get_name()}")
                return False
        return True

    def remove_camera_pipeline(self, idx):
        # Release the requested pad
        if self.camera_sink_pads[idx]:
            compositor = self.compositors[idx]
            compositor.release_request_pad(self.camera_sink_pads[idx])
            self.camera_sink_pads[idx] = None

        elements = self.camera_elements[idx]
        if elements:
            # Set elements to NULL state and remove from pipeline
            for elem in elements:
                elem.set_state(Gst.State.NULL)
                self.pipeline.remove(elem)
            self.camera_elements[idx] = None
            self.v4l2src_elements[idx] = None
            logger.info(f"Removed camera {idx+1} pipeline.")

    def handle_rtmp_error(self, rtmp_sink):
        # Network error detection based on the error type from the message
        logger.info(f"RTMP connection error detected on {rtmp_sink.get_name()}. Retrying...")

        # Set a retry interval (in seconds)
        retry_interval = 10
        GLib.timeout_add_seconds(retry_interval, self.retry_rtmp_connection, rtmp_sink)

    def retry_rtmp_connection(self, rtmp_sink):
        # Check if the stream is enabled
        if not self.is_enabled:
            logger.info("Stream is disabled. Will not attempt to reconnect to RTMP.")
            return False
        # Check if the network is available
        if self.is_network_available():
            logger.info("Network is available. Attempting to reconnect to RTMP.")
            try:
                # Reconnect the RTMP sink
                self.reconnect_rtmp_sink(rtmp_sink)
                return False  # Stop retrying after successful reconnection
            except Exception as e:
                logger.error(f"Error reconnecting RTMP sink: {e}")
                return True  # Retry after the interval if reconnection fails
        else:
            logger.info("Network is still unavailable. Will retry again.")
            return True  # Keep retrying until network is available

    def is_network_available(self):
        # Check for network connectivity (can use ping, socket, or any other method)
        try:
            # A simple check like attempting to open a socket to a reliable server
            import socket
            host = "8.8.8.8"  # Google DNS as an example
            socket.create_connection((host, 53), timeout=5)
            return True
        except socket.error:
            return False

    def reconnect_rtmp_sink(self, rtmp_sink):
        # Attempt to reconnect the RTMP stream
        rtmp_url = self.get_rtmp_url_for_stream(rtmp_sink)  # Retrieve the RTMP URL
        # Ensure that the RTMP URL is not empty
        if not rtmp_url:
            logger.error("ERROR: RTMP URL is empty or invalid. Cannot reconnect.")
            return
        logger.info(f"Attempting to reconnect to RTMP stream: {rtmp_url}")
        # Set the RTMP sink location to the new URL
        rtmp_sink.set_property('location', rtmp_url)

        # Restart the pipeline or the RTMP element
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.set_state(Gst.State.PLAYING)
        logger.info(f"Reconnected to RTMP stream: {rtmp_url}")

    def get_rtmp_url_for_stream(self, rtmp_sink):
        # Iterate over the desired video streams
        for idx, stream in enumerate(self.desired_video_streams):
            # Since camera_num = idx + 1, check for that in the sink name
            if f"rtmpsink{idx+1}" in rtmp_sink.get_name():
                return stream['channel'].get('streamEndpoint', '')
        return ""

    def run_pipeline(self):
        self.loop = GLib.MainLoop()
        try:
            self.loop.run()
        except Exception as e:
            sys.stderr.write(f"\n\n\n*** ERROR: main event loop exited with exception: {e}\n\n\n")
        finally:
            logger.info('Safely stopping and cleaning up the pipeline')
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
                self.pipeline = None

    def __del__(self):
        logger.info(f'Destructor of StreamManager "{self.label}" class')
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None