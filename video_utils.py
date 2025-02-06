import pyudev

def list_cameras():
    context = pyudev.Context()
    cameras = []
    seen_devices = {}
    
    for device in context.list_devices(subsystem='video4linux'):
        if 'DEVNAME' in device:
            video_path = device.device_node

            # Get the unique physical path of the device
            id_path = device.get('ID_PATH', '')
            model = device.get('ID_MODEL', 'Unknown')

            if id_path and id_path not in seen_devices:
                seen_devices[id_path] = video_path
                cameras.append({
                    "name": f"{model} ({id_path})",
                    "path": video_path
                })
            elif not id_path:
                # Fallback for devices without ID_PATH
                unique_id = device.sys_path
                if unique_id not in seen_devices:
                    seen_devices[unique_id] = video_path
                    cameras.append({
                        "name": model,
                        "path": video_path
                    })

    return cameras