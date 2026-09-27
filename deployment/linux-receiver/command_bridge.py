"""Length-framed encrypted WFB injection over authenticated SSH stdin."""
import socket
import fcntl
import json
import os
import tempfile
import struct
import sys
import time
import re
from pathlib import Path


RECEIVER_MACS = ('00:13:ef:f2:13:c1', '88:e6:28:6b:ca:ff', '5c:ff:ff:ac:4a:14')


def receiver_macs():
    """Role bindings are saved by the unprivileged receiver control service."""
    import re
    try:
        path = Path('/mnt/fitlab-ssd/apps/fit-lab-station/data/config/radio-adapters.json')
        slots = json.loads(path.read_text())['slots']
        if (isinstance(slots, list) and len(slots) == 3
                and all(isinstance(mac, str) and re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac) for mac in slots)
                and len(set(slots)) == 3):
            return tuple(slots)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return RECEIVER_MACS


def receiver_interfaces(root=Path('/sys/class/net')):
    """Resolve saved physical identities; USB port and Linux name are irrelevant."""
    macs = receiver_macs()
    found = {mac: [] for mac in macs}
    for entry in sorted(root.iterdir()):
        try:
            mac = (entry / 'address').read_text().strip().lower()
            if mac not in found:
                continue
            usb = (entry / 'device').resolve().parent
            if ((usb / 'idVendor').read_text().strip().lower(),
                    (usb / 'idProduct').read_text().strip().lower()) != ('0bda', '8812'):
                continue
            found[mac].append(entry.name)
        except OSError:
            continue  # Hot-unplug during enumeration is normal.
    # Ambiguous identities must not silently exchange the TX roles.
    return tuple(found[mac][0] if len(found[mac]) == 1 else None for mac in macs)


def read_exact(size):
    data = bytearray()
    while len(data) < size:
        chunk = sys.stdin.buffer.read(size-len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


CHANNELS = tuple(range(1, 15)) + tuple(range(36, 65, 4)) + tuple(range(100, 145, 4)) + (149, 153, 157, 161, 165)
SETTINGS = Path('/mnt/fitlab-ssd/apps/fit-lab-receiver/radio-settings.json')
CONTROL_LOGS = Path('/mnt/fitlab-ssd/apps/fit-lab-station/data/logs')


def interface_ready(interface, root=Path('/sys/class/net')):
    """A reappearing USB interface is not usable until monitor mode is up."""
    if interface is None:
        return False
    try:
        path = root / interface
        return path.joinpath('type').read_text().strip() == '803' and bool(
            int(path.joinpath('flags').read_text().strip(), 16) & 1)
    except (OSError, ValueError):
        return False


class TxSelector:
    def __init__(self):
        self.owner = None
        self.changed = 0
        self.candidate = None
        self.since = 0
        self.switches = 0

    def select(self, available, signals, now, counts=None):
        if not available:
            self.owner = None
            return None
        counts = counts or {}
        strongest_count = max((counts.get(i, 0) for i in available), default=0)
        margin = max(3, strongest_count * .1)
        candidates = [i for i in available if counts.get(i, 0) >= strongest_count-margin] if counts else available
        best = max(candidates, key=lambda i: (signals.get(i, -200), i == self.owner, -i))
        if self.owner not in available:
            chosen = best
        elif (best != self.owner and best in signals
              and (signals[best] >= signals.get(self.owner, -200) + 6
                   or counts.get(best, 0) > counts.get(self.owner, 0) + margin)):
            if self.candidate != best:
                self.candidate, self.since = best, now
            chosen = best if now-self.since >= 3 and now-self.changed >= 10 else self.owner
        else:
            self.candidate = None
            chosen = self.owner
        if chosen != self.owner:
            self.switches += self.owner is not None
            self.owner, self.changed, self.candidate = chosen, now, None
        return self.owner


def control_metrics(now):
    """Fresh per-adapter control downlink RSSI, independent of video/UI."""
    result, counts, stamps = {}, {}, {}
    try:
        with (CONTROL_LOGS/'lan-control/control-rx.log').open('rb') as stream:
            stream.seek(max(0, stream.seek(0, 2)-32768))
            lines = stream.read().decode(errors='replace').splitlines()
        for line in lines:
            match = re.fullmatch(r'(\d+)\s+RX_ANT\s+\S+\s+([0-9a-fA-F]+)\s+(\d+):(-?\d+):(-?\d+):(-?\d+):.*', line)
            if match and 0 <= now-int(match[1])/1000 < 3 and int(match[3]) > 0:
                index = (int(match[2], 16) >> 8) & 255
                if index in (0, 1):
                    stamp = int(match[1])
                    if stamp > stamps.get(index, -1):
                        result[index], counts[index], stamps[index] = int(match[5]), int(match[3]), stamp
                    elif stamp == stamps[index]:
                        result[index] = max(result[index], int(match[5]))
                        counts[index] = max(counts[index], int(match[3]))
    except OSError:
        pass
    return result, counts


def control_signals(now):
    return control_metrics(now)[0]


def save_tuning(channel, width):
    if channel not in CHANNELS or width not in (20, 40):
        raise ValueError('Unsupported radio tuning')
    value = {'channel': channel, 'width': width}
    fd, temporary = tempfile.mkstemp(prefix='.tuning-', dir=SETTINGS.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, SETTINGS)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    print(json.dumps(value), flush=True)


def presence():
    import select
    import time
    import ipaddress
    connection=os.environ.get('SSH_CONNECTION', '').split()
    if len(connection) != 4:
        raise ValueError('Presence requires authenticated SSH')
    address=str(ipaddress.ip_address(connection[0]))
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    folder=SETTINGS.parent/'master-presence'
    folder.mkdir(mode=0o700,exist_ok=True)
    destination=folder/(str(os.getpid())+'.json')
    try:
        while select.select([sys.stdin.buffer], [], [], 4)[0]:
            if sys.stdin.buffer.readline(3) != b'P\n':break
            fd,name=tempfile.mkstemp(prefix='.presence-',dir=folder)
            try:
                with os.fdopen(fd,'w') as stream:
                    json.dump({'address':address,'seen':time.monotonic(),'authenticated':True,'boot_id':boot},stream)
                os.replace(name,destination)
            finally:
                if os.path.exists(name):os.unlink(name)
    finally:
        destination.unlink(missing_ok=True)


def main():
    if sys.argv[1:] == ['--presence']:
        presence()
        return
    if len(sys.argv) == 4 and sys.argv[1] == '--tune':
        save_tuning(int(sys.argv[2]), int(sys.argv[3]))
        return
    if len(sys.argv) != 1: raise ValueError('Unsupported operation')
    # One encoder owns the radio command stream at a time. Concurrent masters
    # otherwise inject incompatible encrypted sessions into the same stream.
    lease = (SETTINGS.parent / 'control.lock').open('a')
    try:
        fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('FIT-LAB: radio control is owned by another station', file=sys.stderr)
        raise SystemExit(75)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interfaces = receiver_interfaces()[:2]
    selector = TxSelector()
    checked, selected = 0, None
    while True:
        header = read_exact(2)
        if header is None: return
        size = struct.unpack('!H', header)[0]
        if not 8 <= size <= 4096: raise ValueError('Invalid frame size')
        data = read_exact(size)
        if data is None: return
        now = time.monotonic()
        if now-checked >= .25 or selected is None or not interface_ready(interfaces[selected]):
            interfaces = receiver_interfaces()[:2]
            available = [i for i, interface in enumerate(interfaces) if interface_ready(interface)]
            # Temporary bench override expires automatically; missing USB still falls back.
            try:
                forced = int(os.environ.get('FIT_LAB_TX_TEST_RX', '0')) - 1
                until = float(os.environ.get('FIT_LAB_TX_TEST_UNTIL', '0'))
                if forced in available and now < until <= now + 600:
                    available = [forced]
            except ValueError:
                pass
            signals, counts = control_metrics(now)
            selected = selector.select(available, signals, now, counts)
            checked = now
            value = dict(updated=now, tx_receiver=selected+1 if selected is not None else None,
                         tx_switches=selector.switches, tx_selection='packets_rssi_hysteresis',
                         boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
            temporary = CONTROL_LOGS/'tx-route.tmp'
            temporary.write_text(json.dumps(value))
            temporary.replace(CONTROL_LOGS/'tx-route.json')
        if selected is not None:
            sender.sendto(data, ('127.0.0.1', 15660+selected))

if __name__ == '__main__':
    main()
