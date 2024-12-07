import subprocess

def get_audio_devices():
    cmd_devices = """arecord -l | grep card"""
    devicesstr = subprocess.run(["bash", "-c", cmd_devices], stdout=subprocess.PIPE)
    device_list = devicesstr.stdout.decode('utf-8')
    devices = []
    for d in device_list.split('\n'):
        if len(d) > 0:
            d_name = ' '.join(d.split(':')[1:])
            d_address = f"hw:{d.split(':')[0].split(' ')[-1]},0"
            devices.append(d_address)
            print(f'Found device #{len(devices)}: address {d_address} description {d_name}')
    return devices

def select_audio_device(silence_audio):
    # Check if audio should be muted
    if silence_audio:
        print('Audio is muted')
        return None

    # Get the list of audio devices
    devices = get_audio_devices()
    device_count = len(devices)

    # Select the appropriate device based on availability
    if device_count > 1:
        print('More than 1 audio input found, using the last one')
        return devices[-1]
    elif device_count == 1:
        print('The only audio input found')
        return devices[0]
    else:
        print('Unable to find audio input, using silence instead')
        return None
