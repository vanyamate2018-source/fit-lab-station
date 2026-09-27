"""Auto-discovered encrypted WFB forwarding with stable physical RX roles."""
import json, socket, subprocess, time, signal
import threading
import os
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


TARGET = '192.168.2.39'
BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def master_targets(now):
    """Use fresh authenticated SSH peers, including a recovered Wi-Fi path."""
    import ipaddress
    targets = set()
    for path in list(Path('/mnt/fitlab-ssd/apps/fit-lab-receiver/master-presence').glob('*.json'))[:64]:
        try:
            value = json.loads(path.read_text())
            address = ipaddress.ip_address(value['address'])
            if (value.get('authenticated') is True and value.get('boot_id') == BOOT_ID
                    and 0 <= now-float(value['seen']) < 3.5
                    and address.version == 4 and not address.is_multicast and not address.is_unspecified):
                targets.add(str(address))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(targets)[:4] or [TARGET]
stop = False
def ending(*_):
    global stop
    stop = True
signal.signal(signal.SIGTERM, ending)
signal.signal(signal.SIGINT, ending)
def led_path(interface):
    for driver in ('rtl88XXau', 'rtl88xxau_wfb', 'rtl8812au'):
        path = Path('/proc/net', driver, interface)
        if path.exists():
            return path
    raise FileNotFoundError(interface)


class UsbLedRegister:
    """RTL8812AU vendor register access when the WFB driver has no procfs API."""
    def __init__(self, interface):
        self.device = Path('/sys/class/net', interface, 'device').resolve().parent
        if (self.device / 'idVendor').read_text().strip() != '0bda':
            raise OSError('Unsupported LED device')

    def write_text(self, command):
        import ctypes
        address, value, width = command.split()
        if address != '4c' or width != '1' or value not in ('20', '28'):
            raise OSError('Unsupported LED register')
        class Control(ctypes.Structure):
            _fields_ = [('request_type', ctypes.c_uint8), ('request', ctypes.c_uint8),
                        ('value', ctypes.c_uint16), ('index', ctypes.c_uint16),
                        ('length', ctypes.c_uint16), ('timeout', ctypes.c_uint32),
                        ('data', ctypes.c_void_p)]
        bus = int((self.device / 'busnum').read_text())
        number = int((self.device / 'devnum').read_text())
        data = ctypes.c_uint8(int(value, 16))
        transfer = Control(0x40, 0x05, 0x4c, 0, 1, 250, ctypes.addressof(data))
        libc = ctypes.CDLL(None, use_errno=True)
        fd = os.open(f'/dev/bus/usb/{bus:03d}/{number:03d}', os.O_RDWR)
        try:
            if libc.ioctl(fd, 0xC0185500, ctypes.byref(transfer)) != 1:
                raise OSError(ctypes.get_errno(), 'LED USB transfer failed')
        finally:
            os.close(fd)


def manual_led(interface):
    try:
        path = led_path(interface)
    except FileNotFoundError:
        return UsbLedRegister(interface)
    if (path / 'led_config').exists():
        (path / 'led_config').write_text('0 0\n')
    elif (path / 'led_enable').exists():
        (path / 'led_enable').write_text('0\n')
    return path / 'write_reg'


def indicators():
    """LED-only master lease. Never accepts commands or configuration."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('0.0.0.0', 60401))
    listener.listen(2)
    listener.settimeout(.25)
    seen = 0
    active = [False] * len(RECEIVER_MACS)
    previous = {}
    written = {}
    for interface in receiver_interfaces():
        if interface is None:
            continue
        try:
            manual_led(interface)
        except OSError:
            pass
    try:
        while not stop:
            try:
                connection, address = listener.accept()
                with connection:
                    connection.settimeout(.25)
                    packet = b''
                    while b'\n' not in packet and len(packet) < 512:
                        chunk = connection.recv(512-len(packet))
                        if not chunk: break
                        packet += chunk
                if address[0] in (*master_targets(time.monotonic()), '127.0.0.1'):
                    message = json.loads(packet)
                    values = message.get('receiving') if isinstance(message, dict) else None
                    if (message.get('type') == 'rx.indicators' and isinstance(values, list)
                            and 1 <= len(values) <= len(RECEIVER_MACS) and all(type(v) is bool for v in values)):
                        active = values + [False] * (len(RECEIVER_MACS) - len(values))
                        seen = time.monotonic()
            except (OSError, ValueError, AttributeError):
                pass
            now = time.monotonic()
            for index, interface in enumerate(receiver_interfaces()):
                if interface is None:
                    continue
                lit = (now-seen < 3 and active[index]) or int(now*2) % 2 == 0
                value = '20' if lit else '28'
                path = None
                try:
                    if previous.get(interface) != value or now-written.get(interface, 0) >= 1:
                        path = manual_led(interface)
                        path.write_text('4c ' + value + ' 1\n')
                        previous[interface] = value
                        written[interface] = now
                except OSError:
                    previous.pop(interface, None)
    finally:
        listener.close()
        for interface in receiver_interfaces():
            if interface is None:
                continue
            try: manual_led(interface).write_text('4c 28 1\n')
            except OSError: pass

def forward_stream(input_port, output_port):
    """Fan out encrypted packets; decoding happens only in a selected viewer."""
    incoming = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    incoming.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
    incoming.bind(('127.0.0.1', input_port))
    incoming.settimeout(.25)
    outgoing = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    outgoing.setblocking(False)
    local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    local.setblocking(False)
    routes, checked = [TARGET], 0
    try:
        while not stop:
            now = time.monotonic()
            if now-checked > .5:
                checked = now
                try:
                    settings = json.loads(Path('/mnt/fitlab-ssd/apps/fit-lab-receiver/outputs.json').read_text())
                    routes = (master_targets(now) if settings.get('master_enabled', True) is True else [])
                    if output_port == 15652 or settings.get('local_enabled', False) is True:
                        routes.insert(0, '127.0.0.1')
                except (OSError, ValueError):
                    routes = (['127.0.0.1'] if output_port == 15652 else []) + master_targets(now)
            try: packet = incoming.recv(65535)
            except socket.timeout: continue
            for target in routes:
                try: (local if target == '127.0.0.1' else outgoing).sendto(packet, (target, output_port))
                except OSError: pass
    finally:
        incoming.close(); outgoing.close(); local.close()


def radio_tuning():
    try:
        value = json.loads(Path('/mnt/fitlab-ssd/apps/fit-lab-receiver/radio-settings.json').read_text())
    except FileNotFoundError:
        value = {'channel':40, 'width':20}
    channels = tuple(range(1,15)) + tuple(range(36,65,4)) + tuple(range(100,145,4)) + (149,153,157,161,165)
    if type(value.get('channel')) is not int or value['channel'] not in channels or value.get('width') not in (20,40):
        raise ValueError('Invalid radio tuning')
    return value['channel'], value['width']


def tune(interface, tuning):
    channel, width = tuning
    subprocess.run(['iw','dev',interface,'set','channel',str(channel),
                    'HT20' if width == 20 else 'HT40+'], check=True, timeout=5)


def usb_identity(interface, mac, root=Path('/sys/class/net')):
    """Keep the actual USB ancestry, never infer it from a network name."""
    entry = root/interface
    if (entry/'address').read_text().strip().lower() != mac:
        raise ValueError('USB identity changed')
    usb = (entry/'device').resolve().parent
    if ((usb/'idVendor').read_text().strip(), (usb/'idProduct').read_text().strip()) != ('0bda', '8812'):
        raise ValueError('Unsupported USB receiver')
    import re
    bus = next(p for p in usb.parents if re.fullmatch(r'usb\d+', p.name))
    controller = bus.parent
    driver = (controller/'driver').resolve()
    return dict(mac=mac, usb=usb, controller=controller, driver=driver)


def empty_usb_controller(controller):
    """All USB roots of this controller must be empty, including USB 2/3 peers."""
    roots = [p for p in controller.glob('usb*') if (p/'idVendor').is_file()]
    return bool(roots) and not any(p.parent != root for root in roots for p in root.rglob('idVendor'))


class UsbRecovery:
    def __init__(self):
        self.devices, self.failed_since, self.attempted = {}, {}, set()
        self.last_attempt = -60.0
        self.lock = threading.Lock()

    def remember(self, index, interface, mac):
        try:
            identity = usb_identity(interface, mac)
        except (OSError, ValueError, StopIteration):
            return
        with self.lock:
            if self.devices.get(index, {}).get('mac') != mac:
                self.attempted.discard(index)
                self.failed_since.pop(index, None)
            self.devices[index] = identity

    def healthy(self, index):
        with self.lock:
            self.failed_since.pop(index, None)
            self.attempted.discard(index)

    def failed(self, index, now):
        with self.lock:
            self.failed_since.setdefault(index, now)
            saved = self.devices.get(index)
            if (not saved or index in self.attempted or now-self.failed_since[index] < 10
                    or now-self.last_attempt < 60 or receiver_macs()[index] != saved['mac']):
                return
            usb, controller, driver = (saved[k] for k in ('usb', 'controller', 'driver'))
            operation = None
            try:
                if usb.exists():
                    interface = receiver_interfaces()[index]
                    if not interface or usb_identity(interface, saved['mac'])['usb'] != usb:
                        return
                    operation = 'device reset'
                    # Child timeout keeps a wedged USB ioctl out of the video worker.
                    code = """import os,fcntl,sys
from pathlib import Path
usb=Path(sys.argv[1]); net=Path('/sys/class/net')/sys.argv[2]
assert (net/'address').read_text().strip().lower()==sys.argv[3]
assert (net/'device').resolve().parent==usb
assert ((usb/'idVendor').read_text().strip(),(usb/'idProduct').read_text().strip())==('0bda','8812')
bus=int((usb/'busnum').read_text());dev=int((usb/'devnum').read_text())
fd=os.open('/dev/bus/usb/%03d/%03d'%(bus,dev),os.O_RDWR)
try: fcntl.ioctl(fd,0x5514,0)
finally: os.close(fd)
"""
                    arguments = [str(usb), interface, saved['mac']]
                else:
                    if (driver.name not in ('xhci-hcd', 'ehci-platform')
                            or not controller.is_relative_to('/sys/devices')
                            or (controller/'driver').resolve() != driver
                            or not empty_usb_controller(controller)):
                        return
                    operation = 'empty controller rebind'
                    code = """import sys
from pathlib import Path
c,d=map(Path,sys.argv[1:]); roots=[p for p in c.glob('usb*') if (p/'idVendor').is_file()]
assert roots and not any(p.parent!=r for r in roots for p in r.rglob('idVendor'))
assert (c/'driver').resolve()==d
try: (d/'unbind').write_text(c.name)
finally:
 if not (c/'driver').exists(): (d/'bind').write_text(c.name)
"""
                    arguments = [str(controller), str(driver)]
                self.attempted.add(index)
                self.last_attempt = now
                print('RX%d USB recovery: %s' % (index+1, operation), flush=True)
                subprocess.run(['/usr/bin/python3', '-c', code, *arguments], check=True,
                               timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as exc:
                print('RX%d USB recovery failed: %s' % (index+1, type(exc).__name__), flush=True)
            finally:
                # A timed-out unbind must still get a bounded rebind attempt.
                if operation == 'empty controller rebind' and not (controller/'driver').exists():
                    try:
                        subprocess.run(['/usr/bin/python3', '-c',
                            'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])',
                            str(driver/'bind'), controller.name], check=True, timeout=5,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except (OSError, subprocess.SubprocessError):
                        print('RX%d USB controller needs reconnect' % (index+1), flush=True)


usb_recovery = UsbRecovery()


def receiver_worker(index):
    last_error = None
    while not stop:
        child = None
        control_children = []
        try:
            mac = receiver_macs()[index]
            interface = receiver_interfaces()[index]
            if interface is None:
                raise FileNotFoundError('USB receiver absent or identity ambiguous')
            if Path('/sys/class/net', interface, 'address').read_text().strip().lower() != mac:
                raise RuntimeError('Receiver identity mismatch')
            usb_recovery.remember(index, interface, mac)
            for command in (['nmcli','device','set',interface,'managed','no'],
                            ['ip','link','set',interface,'down'],
                            ['iw','dev',interface,'set','type','monitor'],
                            ['ip','link','set',interface,'up']):
                subprocess.run(command, check=True, timeout=3)
            applied = radio_tuning()
            tune(interface, applied)
            try: manual_led(interface)
            except OSError: pass  # LED support must not prevent video reception.
            env = dict(os.environ, FITLAB_RX_SLOT=str(index))
            child = subprocess.Popen(['/usr/local/libexec/fit-lab/wfb_rx','-f','-c','127.0.0.1',
                                      '-u','15670','-i','7669206','-p','0',interface], env=env)
            control_children.append(subprocess.Popen(['/usr/local/libexec/fit-lab/wfb_rx',
                '-f','-c','127.0.0.1','-u','15672','-i','7669206','-p','32',interface], env=env))
            if index < 2:  # RX3 contributes reception; TX stays on the established pair.
                control_children.append(subprocess.Popen(['/usr/local/libexec/fit-lab/wfb_tx',
                    '-I',str(15660+index),interface]))
            print('RX%d connected: %s (%s)' % (index+1, interface, mac), flush=True)
            last_error = None
            retry_control = [0, 0]
            mode_checked = 0
            healthy_since = time.monotonic()
            health_confirmed = False
            while not stop and child.poll() is None and Path('/sys/class/net',interface).exists():
                now = time.monotonic()
                if not health_confirmed and now-healthy_since >= 10:
                    usb_recovery.healthy(index)
                    health_confirmed = True
                if now - mode_checked >= 2:
                    mode_checked = now
                    if receiver_interfaces()[index] != interface:
                        raise RuntimeError('Receiver interface changed; reinitializing')
                    if Path('/sys/class/net', interface, 'type').read_text().strip() != '803':
                        raise RuntimeError('Monitor mode lost; reinitializing adapter')
                # An optional command subprocess must not restart a healthy
                # video receiver (and discard its FEC/session history).
                for slot, process in enumerate(control_children):
                    if process.poll() is not None and time.monotonic() >= retry_control[slot]:
                        control_children[slot] = subprocess.Popen(process.args, env=env)
                        retry_control[slot] = time.monotonic() + 1
                target = radio_tuning()
                if target != applied:
                    tune(interface, target)
                    applied = target
                    print('RX%d tuned: channel %d / %d MHz' % (index+1,*target), flush=True)
                time.sleep(.1)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            if last_error != type(exc).__name__:
                print('RX%d waiting: %s' % (index+1, type(exc).__name__), flush=True)
                last_error = type(exc).__name__
        finally:
            children = control_children + ([child] if child is not None else [])
            for process in children:
                if process.poll() is None: process.terminate()
            deadline = time.monotonic() + .5
            for process in children:
                try: process.wait(timeout=max(.001, deadline-time.monotonic()))
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        if not stop:
            usb_recovery.failed(index, time.monotonic())
        # Retry only the failed adapter. The other receiver keeps running.
        for _ in range(2):
            if stop: break
            time.sleep(.1)

relays = [threading.Thread(target=forward_stream,args=ports,daemon=True) for ports in ((15670,15650),(15672,15652))]
for relay in relays: relay.start()
workers = [threading.Thread(target=receiver_worker, args=(i,), daemon=True)
           for i,mac in enumerate(RECEIVER_MACS)]
for worker in workers: worker.start()
led_worker = threading.Thread(target=indicators, daemon=True)
led_worker.start()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    while not stop:
        message = {'protocol':'fit-lab','version':1,'type':'module.hello',
                   'module':{'id':'orangepi3b-0000a40b9a7f','kind':'receiver',
                   'name':'Видеомодуль WFB',
                   'capabilities':['radio.forward.encrypted','rx.dual','rx.triple'], 'receiver_count':sum(name is not None for name in receiver_interfaces())}}
        try:
            for target in (*master_targets(time.monotonic()), '127.0.0.1'):
                sock.sendto(json.dumps(message).encode(),(target,60400))
        except OSError: pass
        time.sleep(.5)
finally:
    sock.close()
    for worker in workers: worker.join(timeout=12)
    led_worker.join(timeout=1)
