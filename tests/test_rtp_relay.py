import socket
import struct
import time
from master.rtp_relay import RtpRelay


def test_forwarding_continues_without_gui_and_stop_releases_port():
    relay = RtpRelay()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sink.bind(('127.0.0.1', 0))
        sink.settimeout(1)
        relay.configure(video=sink.getsockname()[1])
        assert relay.bind('127.0.0.1', 0)
        port = relay.socket.getsockname()[1]
        try:
            for seq in range(20):
                packet = struct.pack('!BBHII', 128, 97, seq, seq * 3000, 42) + b'video'
                sender.sendto(packet, ('127.0.0.1', port))
                assert sink.recvfrom(64)[0] == packet
            state = relay.snapshot()
            assert state['packets'] == 20
            assert state['integrity']['sequence_gaps'] == 0
            assert len(state['frames']) == 20
            assert not relay.snapshot()['frames']
            other = RtpRelay()
            assert not other.bind('127.0.0.1', port)
        finally:
            relay.close()
        assert other.bind('127.0.0.1', port)
        other.close()


def test_opus_copy_for_recording_is_independent_from_playback():
    relay = RtpRelay()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as recording, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        recording.bind(('127.0.0.1', 0))
        recording.settimeout(1)
        relay.configure(record_audio=recording.getsockname()[1])
        assert relay.bind('127.0.0.1', 0)
        try:
            packet = struct.pack('!BBHII', 128, 98, 1, 960, 42) + b'opus'
            sender.sendto(packet, ('127.0.0.1', relay.socket.getsockname()[1]))
            assert recording.recvfrom(64)[0] == packet
            state = relay.snapshot()
            assert state['audio_packets'] == 1
            assert time.monotonic() - state['last_audio_packet'] < 1
            assert state['packets'] == 0
        finally:
            relay.close()
