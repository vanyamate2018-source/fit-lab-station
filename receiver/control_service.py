"""One radio control owner, independent of video windows and decoders."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import time

from shared.control_status import boot_identity
from shared.pairing_store import atomic_write


def key_revision(path):
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except OSError:
        return None


def main():
    from master.lan_control import LanControl
    root = Path(os.environ['FIT_LAB_ROOT'])
    data = Path(os.environ['FIT_LAB_DATA_ROOT'])
    logs = data / 'logs/lan-control'
    logs.mkdir(parents=True, exist_ok=True)
    lock = (logs / 'service.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    key = root / 'private/runcam/gs.key'
    boot = boot_identity()
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    control = None
    revision = None
    retry = last_write = 0
    state = {'state': 'starting'}
    from receiver.usb_registry import ReceiverRegistry
    registry = ReceiverRegistry(data/'config/radio-adapters.json')
    try:
        while running:
            now = time.monotonic()
            current = key_revision(key)
            if current != revision and control is not None:
                control.close()
                control = None
                retry = 0
            revision = current
            if control is None and current is not None and now >= retry:
                try:
                    control = LanControl(logs, key, root)
                except Exception:
                    state = {'state': 'retrying', 'error': 'Восстановление обратного канала'}
                    retry = now + 3
            if control is not None:
                try:
                    state = dict(control.poll(now))
                    try:
                        route = json.loads((data/'logs/tx-route.json').read_text())
                        if route.get('boot_id') == boot and 0 <= now-route.get('updated', 0) < 3:
                            state.update({k: route[k] for k in ('tx_receiver', 'tx_switches', 'tx_selection')})
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                except Exception:
                    control.close()
                    control = None
                    retry = now + 3
                    state = {'state': 'retrying'}
            elif current is None:
                state = {'state': 'waiting', 'error': 'Камера ещё не связана'}
            if now - last_write >= 1:
                try:
                    for change in registry.poll(now):
                        print('RX%d registered: %s' % (change['index']+1, change['mac']), flush=True)
                except (OSError, ValueError):
                    pass  # USB inventory must never interrupt the control channel.
                atomic_write(data / 'logs/control-live.json', json.dumps(dict(
                    state, updated=now, boot_id=boot, owner='service')).encode())
                last_write = now
            time.sleep(.01)
    finally:
        if control is not None:
            control.close()
        atomic_write(data / 'logs/control-live.json', json.dumps(dict(
            state='stopped', updated=time.monotonic(), boot_id=boot, owner='service')).encode())
        lock.close()


if __name__ == '__main__':
    main()
