"""Remember receiver roles, and adopt supported replacement USB radios."""
import json
from pathlib import Path

from shared.pairing_store import atomic_write

DEFAULT_MACS = ('00:13:ef:f2:13:c1', '88:e6:28:6b:ca:ff', '5c:ff:ff:ac:4a:14')
DRIVERS = {'rtl88xxau_wfb', 'rtl88XXau', 'rtl8812au'}


def supported_radios(root=Path('/sys/class/net')):
    found = {}
    for entry in sorted(root.iterdir()):
        try:
            device = (entry/'device').resolve()
            usb = device.parent
            if ((usb/'idVendor').read_text().strip().lower(),
                    (usb/'idProduct').read_text().strip().lower()) != ('0bda', '8812'):
                continue
            if (device/'driver').resolve().name not in DRIVERS:
                continue
            mac = (entry/'address').read_text().strip().lower()
            if not valid_mac(mac):
                continue
            found.setdefault(mac, []).append(entry.name)
        except OSError:
            continue
    return {mac: names[0] for mac, names in found.items() if len(names) == 1}


def valid_mac(value):
    import re
    return isinstance(value, str) and re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', value) is not None


class ReceiverRegistry:
    def __init__(self, path, root=Path('/sys/class/net')):
        self.path, self.root = Path(path), root
        self.slots = list(DEFAULT_MACS)
        self.missing_since = {}
        self.dirty = True
        try:
            saved = json.loads(self.path.read_text())['slots']
            if isinstance(saved, list) and len(saved) == 3 and len(set(saved)) == 3 and all(valid_mac(x) for x in saved):
                self.slots = saved
                self.dirty = False
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.history = {mac: i for i, mac in enumerate(self.slots)}

    def poll(self, now):
        present = supported_radios(self.root)
        changes = []
        for mac in self.slots:
            if mac in present:
                self.missing_since.pop(mac, None)
            else:
                self.missing_since.setdefault(mac, now)
        for mac in sorted(present.keys() - set(self.slots)):
            free = [i for i, old in enumerate(self.slots)
                    if old not in present and now-self.missing_since.get(old, now) >= 8]
            if not free:
                break  # Never evict a connected receiver to adopt a fourth one.
            preferred = self.history.get(mac)
            index = preferred if preferred in free else free[0]
            old = self.slots[index]
            self.slots[index] = mac
            self.history[old], self.history[mac] = index, index
            if len(self.history) > 32:
                self.history = {m: i for i, m in enumerate(self.slots)}
            changes.append({'index': index, 'mac': mac, 'interface': present[mac]})
        self.dirty = self.dirty or bool(changes)
        if self.dirty or not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.path, json.dumps({'version': 1, 'slots': self.slots}).encode())
            self.dirty = False
        return changes
