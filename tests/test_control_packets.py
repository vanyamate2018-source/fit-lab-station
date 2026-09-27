import struct
from shared.control_packets import CAMERA, LOCAL, checksum, echo_reply, ping_packet, records, ssh_records


def reply(seq=3, nonce=b'camera-test'):
    data = bytearray(ping_packet(seq, nonce)[2:])
    data[12:16], data[16:20] = CAMERA, LOCAL
    data[20] = 0
    data[22:24] = b'\0\0'
    data[22:24] = struct.pack('!H', checksum(bytes(data[20:])))
    data[10:12] = b'\0\0'
    data[10:12] = struct.pack('!H', checksum(bytes(data[:20])))
    return struct.pack('!H', len(data)) + data


def test_echo_needs_matching_nonce_and_valid_checksum():
    data = reply()
    assert echo_reply(data, b'camera-test') == 3
    assert echo_reply(data, b'wrong-nonce') is None
    bad = bytearray(data); bad[-1] ^= 1
    assert echo_reply(bad, b'camera-test') is None


def test_truncated_or_fragmented_record_rejected():
    assert not list(records(reply()[:-1]))
    bad = bytearray(reply()); bad[8] |= 0x20
    bad[12:14] = b'\0\0'; bad[12:14] = struct.pack('!H', checksum(bytes(bad[2:22])))
    assert not list(records(bad))


def test_echo_cannot_be_forwarded_to_ssh():
    assert ssh_records(reply()) == b''
    assert echo_reply(ping_packet(3,b'camera-test'), b'camera-test') is None


def test_record_batch_and_trailing_truncation():
    data = reply()
    assert len(list(records(data+data))) == 2
    assert len(list(records(data+b'\xff\xffx'))) == 1


def test_all_authenticated_echoes_in_one_datagram_are_returned():
    from shared.control_packets import echo_replies
    assert list(echo_replies(reply(3)+reply(4)+reply(5, b'wrong'), b'camera-test')) == [3, 4]
