import socket
import time

import pytest

from receiver import camera_fanout


@pytest.fixture
def observer(monkeypatch):
    class Observer:
        def __init__(self, store, link_id):
            assert link_id == 7669206
            self.packets = []

        def feed(self, packet, now):
            self.packets.append(packet)
            if packet == b'bad':
                raise ValueError('malformed synthetic packet')
            return 'a'*24
    monkeypatch.setattr(camera_fanout, 'CameraIdentity', Observer)


def test_relay_observe_and_release_port(tmp_path, observer):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sink.bind(('127.0.0.1', 0))
        sink.settimeout(1)
        relay = camera_fanout.CameraFanout(tmp_path, sink.getsockname()[1], '127.0.0.1', listen_port=0)
        port = relay.listen_port
        try:
            for packet in (b'bad', b'\x00\xffsynthetic encrypted datagram'):
                sender.sendto(packet, ('127.0.0.1', port))
                assert sink.recvfrom(65535)[0] == packet
            deadline = time.monotonic()+1
            while not relay.snapshot(time.monotonic()) and time.monotonic() < deadline:
                time.sleep(.005)
            snapshot = relay.snapshot(time.monotonic())
            assert snapshot[0]['identity'] == 'a'*24
            assert relay.snapshot(snapshot[0]['last_seen']+3) == []
            assert relay.snapshot(snapshot[0]['last_seen']-1) == []
            assert len(relay.identity.packets) == 2
        finally:
            relay.close()
        assert not relay.worker.is_alive()
        relay.close()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as replacement:
            replacement.bind(('0.0.0.0', port))


def test_peer_filter_and_explicit_bind_failure(tmp_path, observer):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sink.bind(('127.0.0.1', 0))
        sink.settimeout(.2)
        relay = camera_fanout.CameraFanout(tmp_path, sink.getsockname()[1], '192.0.2.1', listen_port=0)
        try:
            sender.sendto(b'wrong peer', ('127.0.0.1', relay.listen_port))
            with pytest.raises(socket.timeout):
                sink.recvfrom(65535)
            assert relay.identity.packets == []
            assert relay.snapshot(time.monotonic()) == []
            with pytest.raises(OSError):
                camera_fanout.CameraFanout(tmp_path, sink.getsockname()[1], '127.0.0.1', listen_port=relay.listen_port)
        finally:
            relay.close()
