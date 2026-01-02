"""Audio device utilities for listing and managing audio devices."""

import subprocess

def get_audio_devices():
    """List all available audio devices."""
    cmd_devices = """arecord -l | grep card"""
    devicesstr = subprocess.run(["bash", "-c", cmd_devices], stdout=subprocess.PIPE)
    device_list = devicesstr.stdout.decode('utf-8')
    devices = []
    for d in device_list.split('\n'):
        if len(d) > 0:
            d_name = d.split(':')[1].strip().split(' ')[0]
            d_address = f"hw:{d.split(':')[0].split(' ')[-1]},0"
            devices.append({
                'name': d_name,
                'path': d_address
            })

    return devices

