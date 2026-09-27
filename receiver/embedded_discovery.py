"""Authenticate camera announcements from the installed receiver's local fanout.

Does not retune the shared radios or disturb the remote master's video.
"""
import json
import os
from pathlib import Path
import signal
import socket
import time

from receiver.camera_identity import CameraIdentity
from shared.pairing_store import PairingStore
from shared.receiver_outputs import update


def main():
    root = Path(os.environ['FIT_LAB_DATA_ROOT'])
    identities = CameraIdentity(PairingStore(root), 7669206)
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    parent, seen, last = os.getppid(), {}, 0.0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 15650))
        sock.settimeout(.05)
        update(local_enabled=True)
        try:
            while not stopped and os.getppid() == parent:
                now = time.monotonic()
                try:
                    packet, peer = sock.recvfrom(65535)
                    identity = identities.feed(packet, now) if peer[0] == '127.0.0.1' else None
                    if identity:
                        seen[identity] = dict(identity=identity, last_seen=now)
                except socket.timeout:
                    pass
                if now-last >= .5:
                    print('FITLAB_EVENT '+json.dumps(dict(state='camera_discovery',
                          cameras=[v for v in seen.values() if now-v['last_seen'] < 5],
                          receivers=[], tx_requested=False)), flush=True)
                    last = now
        finally:
            update(local_enabled=False)


if __name__ == '__main__':
    main()
