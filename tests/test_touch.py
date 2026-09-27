import pytest
from shared.touch import decode_qdtech


def frame(slots, count=None):
    packet = bytearray(56)
    packet[0] = 1
    for index, (ident, down, x, y) in enumerate(slots):
        offset = 1+index*5
        packet[offset] = ident | (0x40 if down else 0)
        packet[offset+1:offset+3] = x.to_bytes(2, 'little')
        packet[offset+3:offset+5] = y.to_bytes(2, 'little')
    packet[55] = len(slots) if count is None else count
    return bytes(packet)


def test_multiple_fingers_release_and_padding():
    # Hardware advertises 10 slots but sends 5 valid slots; padding is not input.
    packet = bytearray(frame([(1, True, 256, 300), (2, True, 768, 150)], 5))
    packet[26:51] = b'\xff'*25
    points = decode_qdtech(packet)
    assert [(p.id, p.x, p.y) for p in points] == [(1,.25,.5), (2,.75,.25)]
    assert len(decode_qdtech(frame([(1, False, 256, 300), (2, True, 768, 150)]))) == 1
    assert decode_qdtech(frame([(1, False, 256, 300)])) == []


def test_reject_malformed_reports():
    for packet in (b'\x01', frame([(1, True, 2000, 0)]), frame([(1, True, 1, 2),(1,True,2,3)]), frame([], 11)):
        with pytest.raises(ValueError):
            decode_qdtech(packet)
