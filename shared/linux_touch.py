"""Read-only discovery of direct touch devices; native Linux owns input events."""
from pathlib import Path
import struct


def bitmap(text):
    width = struct.calcsize('P') * 2
    return int(''.join(word.zfill(width) for word in text.split()), 16)


def discover(root=Path('/sys/class/input')):
    devices = []
    for entry in sorted(Path(root).glob('event*')):
        device = entry / 'device'
        try:
            props = bitmap((device / 'properties').read_text())
            axes = bitmap((device / 'capabilities/abs').read_text())
            direct = bool(props & (1 << 1))
            xy = all(axes & (1 << bit) for bit in (0, 1))
            mt_xy = all(axes & (1 << bit) for bit in (0x35, 0x36))
            if not direct or not (xy or mt_xy):
                continue
            devices.append(dict(name=(device/'name').read_text().strip(),
                vendor=(device/'id/vendor').read_text().strip().lower(),
                product=(device/'id/product').read_text().strip().lower(),
                event='/dev/input/'+entry.name, native=True,
                multitouch=bool(mt_xy and axes & (1 << 0x2f))))
        except (OSError, ValueError):
            continue  # Device can disappear between sysfs reads.
    return devices
