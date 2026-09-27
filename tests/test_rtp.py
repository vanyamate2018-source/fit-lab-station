import struct
import pytest
from shared.rtp import Header, SequenceTracker, parse


def packet(seq=10, flags=0x80, extra=b"", payload=b"\x26\x01"):
    return struct.pack("!BBHII", flags, 96, seq, 90000, 123) + extra + payload


def test_rtp_header_extensions_padding():
    assert parse(packet()).sequence == 10
    assert parse(packet(flags=0x91, extra=b"\0" * 4 + b"\xbe\xde\0\1" + b"\0" * 4)).ssrc == 123
    assert parse(packet(flags=0xa0, payload=b"\x26\x01\0\x02")).payload_type == 96


@pytest.mark.parametrize("data", [b"", packet(flags=0x8f), packet(flags=0x90),
    packet(flags=0x90, extra=b"\xbe\xde\xff\xff"), packet(flags=0xa0, payload=b"\0"),
    packet(flags=0xa0, payload=b"\xff"), packet(payload=b""), packet(flags=0x40)])
def test_malformed_rejected(data):
    with pytest.raises(ValueError):
        parse(data)


def test_wrap_duplicate_late_fill_and_new_source():
    tracker = SequenceTracker()
    for seq in (65534, 0, 65535, 0, 1):
        tracker.observe(Header(seq, 0, 123, 96), "camera")
    assert tracker.snapshot() == dict(invalid=0, duplicates=1, reordered=1, sequence_gaps=0, source_restarts=0)
    tracker.observe(Header(40000, 0, 234, 96), "camera")
    assert tracker.restarts == 1 and tracker.gaps == 0


def test_same_ssrc_restart_requires_two_consecutive_packets():
    tracker = SequenceTracker()
    for seq in (30000, 30001, 0, 1, 2):
        tracker.observe(Header(seq, 0, 123, 96), "camera")
    assert tracker.gaps == 0 and tracker.restarts == 1
