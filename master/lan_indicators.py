"""Coalesced LED updates must never hold the radio telemetry reader."""
import json
import socket
import threading


class LanIndicators:
    def __init__(self, target):
        self.target = target
        self.closed = threading.Event()
        self.changed = threading.Event()
        self.payload = None
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def update(self, receivers):
        self.payload = (json.dumps({'type': 'rx.indicators', 'receiving':
            [r['connection'] == 'receiving' for r in receivers]}) + '\n').encode()
        self.changed.set()

    def run(self):
        while not self.closed.is_set():
            if not self.changed.wait(.25):
                continue
            self.changed.clear()
            payload = self.payload
            if self.closed.is_set():
                break
            try:
                with socket.create_connection(self.target, timeout=.2) as connection:
                    connection.sendall(payload)
            except OSError:
                pass

    def close(self):
        self.closed.set()
        self.changed.set()
        self.worker.join(.5)
