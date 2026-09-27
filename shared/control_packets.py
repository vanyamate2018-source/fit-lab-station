"""Strict WFB IP records and nonce-checked camera echo; no payload logging."""
import socket
import struct

LOCAL = socket.inet_aton('10.5.0.1')
CAMERA = socket.inet_aton('10.5.0.10')


def checksum(data):
    data += b'\0' if len(data) % 2 else b''
    total = sum(struct.unpack('!%dH' % (len(data) // 2), data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def records(data):
    while len(data) >= 2:
        length = struct.unpack_from('!H', data)[0]
        data = data[2:]
        if length < 20 or length > len(data):
            return
        packet, data = data[:length], data[length:]
        offset = (packet[0] & 15) * 4
        if (packet[0] >> 4 == 4 and 20 <= offset <= len(packet)
                and struct.unpack_from('!H', packet, 2)[0] == len(packet)
                and not (struct.unpack_from('!H', packet, 6)[0] & 0x3fff)
                and checksum(packet[:offset]) == 0):
            yield packet, offset


def ping_packet(seq, nonce):
    icmp = struct.pack('!BBHHH', 8, 0, 0, 0x464c, seq) + nonce
    icmp = icmp[:2] + struct.pack('!H', checksum(icmp)) + icmp[4:]
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(icmp), seq, 0, 32, 1, 0, LOCAL, CAMERA)
    ip = ip[:10] + struct.pack('!H', checksum(ip)) + ip[12:]
    packet = ip + icmp
    return struct.pack('!H', len(packet)) + packet


def echo_replies(data, nonce):
    for packet, offset in records(data):
        if (packet[9] == 1 and packet[12:16] == CAMERA and packet[16:20] == LOCAL
                and len(packet) == offset + 8 + len(nonce) and packet[offset:offset+2] == b'\0\0'
                and packet[offset+4:offset+6] == b'FL' and packet[offset+8:] == nonce
                and checksum(packet[offset:]) == 0):
            yield struct.unpack_from('!H', packet, offset+6)[0]


def echo_reply(data, nonce):
    return next(echo_replies(data, nonce), None)


def ssh_records(data, outbound=False):
    result = bytearray()
    for packet, offset in records(data):
        source, target = (LOCAL, CAMERA) if outbound else (CAMERA, LOCAL)
        port_offset = offset + 2 if outbound else offset
        if (packet[9] == 6 and packet[12:16] == source and packet[16:20] == target
                and len(packet) >= offset+20 and packet[port_offset:port_offset+2] == b'\0\x16'):
            result.extend(struct.pack('!H', len(packet)) + packet)
    return bytes(result)
