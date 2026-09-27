"""Relay encrypted WFB datagrams and observe authenticated camera identities."""
from collections import OrderedDict
import socket
import threading
import time

from receiver.camera_identity import CameraIdentity
from shared.pairing_store import PairingStore


class CameraFanout:
    def __init__(self, root, output_port, expected_peer, *, listen_port=15650):
        self.identity = CameraIdentity(PairingStore(root), 7669206)
        self.expected_peer = expected_peer
        self.destination = ('127.0.0.1', output_port)
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.seen = OrderedDict()
        self.input = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.output = None
        try:
            # No reuse: a second relay must fail explicitly rather than steal traffic.
            self.input.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
            self.input.bind(('0.0.0.0', listen_port))
            self.listen_port = self.input.getsockname()[1]
            self.input.settimeout(.1)
            self.output = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.output.setblocking(False)
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()
        except BaseException:
            self.input.close()
            if self.output is not None:
                self.output.close()
            raise

    def _run(self):
        while not self.closed.is_set():
            try:
                packet, peer = self.input.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if peer[0] != self.expected_peer:
                continue
            try:
                self.output.sendto(packet, self.destination)
            except OSError:
                pass
            now = time.monotonic()
            try:
                identity = self.identity.feed(packet, now)
            except Exception:
                # Observation must never interrupt the video relay.
                continue
            if identity:
                with self.lock:
                    self.seen[identity] = now
                    self.seen.move_to_end(identity)
                    while len(self.seen) > 64:
                        self.seen.popitem(last=False)

    def snapshot(self, now):
        with self.lock:
            return [{'identity': identity, 'last_seen': stamp}
                    for identity, stamp in self.seen.items() if 0 <= now-stamp < 3]

    def close(self):
        self.closed.set()
        self.input.close()
        self.worker.join(.5)
        self.output.close()
