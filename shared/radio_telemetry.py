"""Incremental parsing of the pinned wfb_rx text statistics (not video data)."""
from __future__ import annotations

import re
import time
from pathlib import Path

FIELDS = (
    "incoming_packets", "incoming_bytes", "decrypt_errors", "session_packets",
    "data_packets", "unique_packets", "fec_recovered", "lost_packets",
    "bad_packets", "outgoing_packets", "outgoing_bytes",
)


class RadioTelemetry:
    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.pending = ""
        self.totals = dict.fromkeys(FIELDS, 0)
        self.latest: dict = {}
        self.last_antenna = 0.0

    def feed(self, text: str, now: float) -> None:
        self.pending += text
        lines = self.pending.split("\n")
        self.pending = lines.pop()[-8192:]
        for line in lines:
            match = re.search(r"\bPKT\s+([0-9]+(?::[0-9]+){10})(?:\s|$)", line)
            if match:
                values = dict(zip(FIELDS, map(int, match[1].split(":"))))
                self.latest.update(values)
                for key, value in values.items():
                    self.totals[key] += value
            match = re.search(r"\bRX_ANT\s+\S+\s+\S+\s+(\d+):(-?\d+):(-?\d+):(-?\d+):(\d+):(\d+):(\d+)", line)
            if match:
                self.latest.update(rssi_dbm=int(match[3]), snr_db=int(match[6]))
                self.last_antenna = now

    def read(self) -> dict:
        now = time.monotonic()
        try:
            with self.path.open(encoding="utf-8", errors="replace") as stream:
                stream.seek(self.offset)
                self.feed(stream.read(262144), now)
                self.offset = stream.tell()
        except FileNotFoundError:
            pass
        return {"interval": dict(self.latest), "totals": dict(self.totals),
                "antenna_fresh": bool(self.last_antenna and now - self.last_antenna < 3)}
