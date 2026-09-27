"""Exclusive, short-lived radio SSH leases; never replay application commands."""
import atexit
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_idle = {}


def identity(root, host, username, password):
    from shared.pairing_store import PairingStore
    root = Path(root)
    store = PairingStore(root)
    active = store.read(store.active_path) or {}
    pin = active.get('ssh_fingerprint')
    if not pin:
        return None
    known = (root / 'config/camera_known_hosts').read_bytes()
    secret = hashlib.sha256((password or '').encode()).digest()
    return (str(root.resolve()), host, username, pin, hashlib.sha256(known).digest(), secret)


class Lease:
    def __init__(self, client, key):
        self.client, self.key, self.closed = client, key, False

    def __getattr__(self, name):
        if self.closed:
            raise RuntimeError('Camera connection lease is closed')
        return getattr(self.client, name)

    def close(self):
        if self.closed:
            return
        self.closed = True
        transport = self.client.get_transport()
        if sys.exc_info()[0] is not None or not transport or not transport.is_active():
            self.client.close()
            return
        with _lock:
            old = _idle.pop(self.key, None)
            _idle[self.key] = (self.client, time.monotonic())
        if old:
            old[0].close()


def acquire(key, connect):
    if key is None:
        return connect()
    now = time.monotonic()
    with _lock:
        stale = [_idle.pop(k)[0] for k in list(_idle) if k != key or now-_idle[k][1] > 45]
        cached = _idle.pop(key, None)
    for client in stale:
        client.close()
    if cached:
        client = cached[0]
        try:
            transport = client.get_transport()
            if not transport or not transport.is_active() or not transport.is_authenticated():
                raise OSError('Inactive camera session')
            # Read-only liveness check before handing a connection to a writer.
            from master.camera_radio import command
            code, _ = command(client, 'true', timeout=2)
            if code:
                raise OSError('Camera liveness check failed')
            return Lease(client, key)
        except Exception:
            client.close()
    return Lease(connect(), key)


@atexit.register
def close_all():
    with _lock:
        clients = [value[0] for value in _idle.values()]
        _idle.clear()
    for client in clients:
        client.close()
