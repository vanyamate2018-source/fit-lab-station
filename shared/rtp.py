"""Bounded RTP structure and sequence diagnostics; no video payload is retained."""
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class Header:
    sequence: int
    timestamp: int
    ssrc: int
    payload_type: int


def parse(data):
    if len(data) < 12 or data[0] >> 6 != 2 or 192 <= data[1] <= 223:
        raise ValueError("Invalid RTP header")
    offset = 12 + (data[0] & 15) * 4
    if offset > len(data):
        raise ValueError("Truncated CSRC")
    if data[0] & 16:
        if offset + 4 > len(data):
            raise ValueError("Truncated extension")
        words = int.from_bytes(data[offset + 2:offset + 4], "big")
        offset += 4 + words * 4
    end = len(data)
    if data[0] & 32:
        padding = data[-1]
        if not padding or padding > end - offset:
            raise ValueError("Invalid padding")
        end -= padding
    if offset >= end:
        raise ValueError("Empty or truncated payload")
    sequence, timestamp, ssrc = struct.unpack_from("!HII", data, 2)
    return Header(sequence, timestamp, ssrc, data[1] & 127)


class SequenceTracker:
    """RFC3550-style restart probation; late arrivals reduce pending gaps.

    Gaps count missing RTP sequence numbers, NOT measured RF losses. A bounded
    window prevents corrupted sequences or very old packets growing memory.
    """
    def __init__(self):
        self.invalid = self.duplicates = self.reordered = self.gaps = self.restarts = 0
        self.source = None
        self.highest = None
        self.seen = set()
        self.missing = set()
        self.bad_sequence = None

    def observe(self, header, source):
        identity = (source, header.ssrc, header.payload_type)
        if identity != self.source or self.highest is None:
            if self.highest is not None:
                self.restarts += 1
            self.source, self.highest = identity, header.sequence
            self.seen, self.missing = {self.highest}, set()
            self.bad_sequence = None
            return
        delta = (header.sequence - (self.highest & 65535) + 32768) % 65536 - 32768
        if delta > 3000 or delta < -1024:
            if header.sequence == self.bad_sequence:
                self.restarts += 1
                self.highest = header.sequence
                self.seen, self.missing = {self.highest}, set()
                self.bad_sequence = None
            else:
                self.bad_sequence = (header.sequence + 1) & 65535
            return
        self.bad_sequence = None
        extended = self.highest + delta
        if extended in self.seen:
            self.duplicates += 1
            return
        if delta > 0:
            self.gaps += delta - 1
            self.missing.update(range(self.highest + 1, extended))
            self.highest = extended
        else:
            self.reordered += 1
            if extended in self.missing:
                self.missing.remove(extended)
                self.gaps -= 1
        self.seen.add(extended)
        cutoff = self.highest - 1024
        # Prune periodically instead of copying sets on every video packet.
        if len(self.seen) > 2048 or len(self.missing) > 4096:
            self.seen = {n for n in self.seen if n >= cutoff}
            self.missing = {n for n in self.missing if n >= cutoff}

    def snapshot(self):
        return {"invalid": self.invalid, "duplicates": self.duplicates,
                "reordered": self.reordered, "sequence_gaps": self.gaps,
                "source_restarts": self.restarts}
