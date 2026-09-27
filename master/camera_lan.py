"""Bounded camera discovery on local Ethernet and Wi-Fi networks."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
from pathlib import Path
from queue import SimpleQueue, Empty
import socket
from threading import Event
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkInterface
from master.viewer_network import is_lan_address


def ethernet_hosts():
    hosts = set()
    own = set()
    networks = set()
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if interface.type() not in (QNetworkInterface.InterfaceType.Ethernet,
                                    QNetworkInterface.InterfaceType.Wifi):
            continue
        if not (flags & QNetworkInterface.InterfaceFlag.IsUp and flags & QNetworkInterface.InterfaceFlag.IsRunning):
            continue
        for entry in interface.addressEntries():
            address = entry.ip().toString()
            if not is_lan_address(address):
                continue
            prefix = entry.prefixLength()
            if not 24 <= prefix <= 30:
                continue  # Never scan a broad enterprise subnet or VPN.
            network = ipaddress.ip_network(f'{address}/{prefix}', strict=False)
            own.add(address)
            networks.add(network)
    # Bound each physical LAN, not the combined list: otherwise a second
    # camera network disappears behind the first /24. Never probe ourselves.
    for network in sorted(networks)[:4]:
        hosts.update(str(ip) for ip in network.hosts())
    return sorted(hosts - own, key=ipaddress.ip_address)


def probe(host, known_cameras=None):
    ports = []
    known = (known_cameras or {}).get(host)
    # Avoid a throw-away SSH connection before the real fingerprint exchange.
    # Small camera SSH daemons can throttle repeated unauthenticated sessions.
    for port in ((80, 554, 22) if known else (80, 554)):
        try:
            with socket.create_connection((host, port), timeout=.3):
                ports.append(port)
        except OSError:
            pass
    if not ports:
        return None
    from master.camera import discover_candidate
    identities = {p['fingerprint']: p for p in (known_cameras or {}).values() if p.get('fingerprint')}
    candidate = discover_candidate(host, fallback=False, fingerprint_only_if_video=not bool(known),
                                   known_identities=identities)
    if candidate.get('state') != 'found':
        return None
    candidate['ports'] = ports
    if known and candidate.get('candidate_fingerprint') == known.get('fingerprint'):
        candidate['family'] = known['family']
    if not candidate.get('video_service_available') and not openipc_candidate(candidate):
        candidate['family'] = 'Сетевое устройство'
    return candidate


def discover_hosts(hosts, on_found=None, cancel=None, known_cameras=None):
    results = []
    pool = ThreadPoolExecutor(max_workers=32)
    hosts = sorted(dict.fromkeys(hosts), key=lambda host: host not in (known_cameras or {}))
    futures = [pool.submit(probe, host, known_cameras) if known_cameras else pool.submit(probe, host) for host in hosts]
    try:
        for future in as_completed(futures):
            if cancel is not None and cancel.is_set():
                break
            try:
                item = future.result()
            except Exception:
                continue  # One malformed device cannot discard other cameras.
            if item is not None and openipc_candidate(item):
                results.append(item)
                if on_found:
                    on_found(item)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def openipc_candidate(device):
    family = str(device.get('family', '')).lower()
    return 'openipc' in family or 'majestic' in family


def camera_devices(devices, known_fingerprints=()):
    """Show OpenIPC-compatible cameras, never generic RTSP/TP-Link devices."""
    grouped = {}
    for device in devices:
        fingerprint = device.get('candidate_fingerprint')
        if not openipc_candidate(device) and fingerprint not in known_fingerprints:
            continue
        key = fingerprint or device['host']
        if key not in grouped:
            grouped[key] = dict(device, addresses=[device['host']])
        elif device['host'] not in grouped[key]['addresses']:
            grouped[key]['addresses'].append(device['host'])
    return list(grouped.values())


class LanDeviceDiscovery(QObject):
    changed = Signal(list)
    scanningChanged = Signal(bool)

    def __init__(self, parent=None, data_root=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.closed = False
        self.last_hosts = None
        self.next_scan = 0
        self.devices = {}
        self.updates = SimpleQueue()
        self.cancel = Event()
        self.data_root = Path(data_root) if data_root else None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def poll(self):
        if self.closed:
            return
        if self.future is not None:
            changed = False
            while True:
                try:
                    item = self.updates.get_nowait()
                except Empty:
                    break
                if self.devices.get(item['host']) != item:
                    self.devices[item['host']] = item
                    changed = True
            if changed:
                self.changed.emit(list(self.devices.values()))
            if self.future.done():
                try:
                    devices = {d['host']: d for d in self.future.result()}
                    if devices != self.devices:
                        self.devices = devices
                        self.changed.emit(list(devices.values()))
                except Exception:
                    pass  # A failed scan is not proof all devices disconnected.
                self.future = None
                self.timer.setInterval(1000)
                self.scanningChanged.emit(False)
            return
        hosts = ethernet_hosts()
        if hosts != self.last_hosts or time.monotonic() >= self.next_scan:
            self.last_hosts = hosts
            self.next_scan = time.monotonic() + 20
            known = {}
            if self.data_root:
                for path in (self.data_root / 'config/cameras').glob('*.json'):
                    try:
                        profile = json.loads(path.read_text())
                        if openipc_candidate(profile) and profile.get('fingerprint') and profile.get('host'):
                            known[profile['host']] = profile
                    except (OSError, ValueError):
                        continue
            self.future = self.pool.submit(discover_hosts, hosts, self.updates.put, self.cancel, known)
            self.timer.setInterval(250)
            self.scanningChanged.emit(True)

    def scan_now(self):
        if self.future is not None:
            return  # Repeated taps share the current scan.
        self.next_scan = 0
        self.poll()

    def close(self):
        self.closed = True
        self.cancel.set()
        self.timer.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
