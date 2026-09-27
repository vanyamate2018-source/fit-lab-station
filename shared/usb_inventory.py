"""Small read-only IOKit inventory, without spawning ioreg during reception."""
import ctypes
from functools import lru_cache
from pathlib import Path
import sys


class Device(ctypes.Structure):
    _fields_ = [('address', ctypes.c_uint32), ('location', ctypes.c_uint32)]


@lru_cache(maxsize=1)
def library():
    if sys.platform != 'darwin':
        return None
    path = Path(__file__).resolve().parents[2] / 'data/cache/native/usb-inventory.dylib'
    try:
        lib = ctypes.CDLL(str(path))
        lib.fitlab_usb_inventory.argtypes = [ctypes.c_uint32, ctypes.c_uint32,
                                             ctypes.POINTER(Device), ctypes.c_size_t]
        lib.fitlab_usb_inventory.restype = ctypes.c_int
        return lib
    except OSError:
        return None


def linux_devices(root=Path('/sys/bus/usb/devices')):
    import zlib
    devices = []
    for path in sorted(Path(root).iterdir()):
        try:
            if ((path/'idVendor').read_text().strip().lower(), (path/'idProduct').read_text().strip().lower()) != ('0bda','8812'):
                continue
            devices.append({'address': int((path/'devnum').read_text()),
                            'location': zlib.crc32(path.name.encode()), 'path': path.name})
        except (OSError, ValueError):
            continue
    return devices


def fast_devices():
    if sys.platform == 'linux':
        return linux_devices()
    lib = library()
    if lib is None:
        return None  # Caller retains its asynchronous legacy fallback.
    devices = (Device * 16)()
    count = lib.fitlab_usb_inventory(0x0bda, 0x8812, devices, len(devices))
    if count < 0 or count > len(devices):
        raise OSError('USB inventory unavailable')
    return sorted([{'address': d.address, 'location': d.location}
                   for d in devices[:count]], key=lambda d: d['location'])
