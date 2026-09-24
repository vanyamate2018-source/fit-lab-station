import socket
import threading

from master.core import StationCore
from master.discovery import DiscoveryServer
from receiver.beacon import build_receiver_announcement, send_announcement
from shared.models import ModuleKind
from shared.wire import WireProtocolError, decode_announcement, encode_announcement


def test_announcement_round_trip() -> None:
    source = build_receiver_announcement(module_id="receiver-1")
    decoded = decode_announcement(encode_announcement(source))

    assert decoded.module_id == "receiver-1"
    assert decoded.kind is ModuleKind.RECEIVER
    assert "video.rx" in decoded.capabilities


def test_invalid_packet_is_rejected() -> None:
    try:
        decode_announcement(b"not-json")
    except WireProtocolError:
        pass
    else:
        raise AssertionError("invalid packet must be rejected")


def test_localhost_udp_discovery() -> None:
    station = StationCore()
    server = DiscoveryServer(station)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()

        result_box = []

        def receive() -> None:
            result_box.append(server.receive_once(sock))

        thread = threading.Thread(target=receive, daemon=True)
        thread.start()

        announcement = build_receiver_announcement(module_id="receiver-net")
        send_announcement(host, port, announcement)

        thread.join(timeout=2.0)

    assert result_box
    assert result_box[0].accepted is True
    assert station.registry.get("receiver-net") is not None
