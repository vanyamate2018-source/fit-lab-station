"""Receive-only discovery on two adapters, before a video session is selected."""
import fcntl
import os
from pathlib import Path
import selectors
import signal
import socket
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from receiver import local_radio as base
from receiver.camera_identity import CameraIdentity
from receiver.dual_radio import inventory
from receiver.recovery import RadioRecovery
from receiver.resilient_radio import Backend
from shared.pairing_store import PairingStore
from shared.radio_settings import receiver_settings


def run():
    store = PairingStore(base.ROOT / 'data')
    store.guard()
    profiles = store.profiles()
    channels = []
    for profile in profiles:
        config = profile.get('receiver_config', {})
        tuning = receiver_settings(config['radio_channel'], config['radio_width'])
        if tuning not in channels:
            channels.append(tuning)
    if not channels:
        return
    logs = Path(tempfile.mkdtemp(prefix='camera-search-', dir=base.ROOT / 'data/logs'))
    parent = os.getppid()
    sockets = []
    recovery = None
    with (base.ROOT / 'data/logs/.fit-lab-radio-prepare.lock').open('a') as lock, ThreadPoolExecutor(max_workers=1) as pool:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            for _ in range(2):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind(('127.0.0.1', 0))
                sock.setblocking(False)
                sockets.append(sock)
            tables = {name: base.TABLE_ROOT / filename for name, (filename, _) in base.TABLE_BLOBS.items()}
            backend = Backend(logs, tables, [s.getsockname()[1] for s in sockets])
            backend.assisted_recovery = False  # Different frequencies are intentional during discovery.
            backend.discovery_channels = channels
            recovery = RadioRecovery(backend)
            identities = CameraIdentity(store, base.LINK_ID)
            seen = {}
            pending = pool.submit(inventory, True)
            last_scan = last_event = 0
            with selectors.DefaultSelector() as mux:
                for index, sock in enumerate(sockets):
                    mux.register(sock, selectors.EVENT_READ, index)
                while os.getppid() == parent:
                    now = time.monotonic()
                    devices = None
                    if pending is not None and pending.done():
                        try:
                            devices = pending.result()
                        except (OSError, ValueError):
                            pass
                        pending, last_scan = None, now
                    if pending is None and now - last_scan > .5:
                        pending = pool.submit(inventory, True)
                    recovery.tick(now, devices)
                    jobs = [j for j in recovery.jobs.values() if j.index is not None and j.phase == 'receiving']
                    for job in jobs:
                        # With two saved frequencies and two adapters neither
                        # adapter needs to hop. Larger lists rotate fairly.
                        if len(channels) > len(jobs) and now - job.started > 8:
                            position = channels.index(job.tuning)
                            recovery.retune(job, channels[(position + max(1, len(jobs))) % len(channels)], now)
                    for selected, _ in mux.select(.025):
                        for _ in range(32):
                            try:
                                packet, _ = selected.fileobj.recvfrom(65535)
                            except BlockingIOError:
                                break
                            recovery.received(selected.data, now)
                            identity = identities.feed(packet, now)
                            if identity:
                                job = next((j for j in jobs if j.index == selected.data), None)
                                seen[identity] = dict(identity=identity, last_seen=now,
                                                      receiver=selected.data + 1, tuning=job.tuning if job else {})
                    if now - last_event >= .5:
                        base.event(state='camera_discovery', cameras=[v for v in seen.values() if now - v['last_seen'] < 5],
                                   receivers=recovery.receivers, log_directory=str(logs), tx_requested=False)
                        last_event = now
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            if recovery:
                recovery.close()
                from receiver.process_cleanup import stop_children
                pending_pids = stop_children(job.process for job in recovery.jobs.values())
                base.event(state='discovery_finished', shutdown_pending_pids=pending_pids)
            for sock in sockets:
                sock.close()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        run()
    except KeyboardInterrupt:
        pass
    except Exception:
        base.event(state='discovery_error', error='Поиск камер временно недоступен')
