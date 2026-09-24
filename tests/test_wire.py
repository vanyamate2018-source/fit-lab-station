import socket
import threading
import time

from master.core import StationCore
from master.discovery import DiscoveryServer
from receiver.beacon import (
    build_receiver_announcement,
    build_receiver_heartbeat,
    send_announcement,
)
from shared.models import ModuleKind, ModuleState
from shared.wire import (
    WireProtocolError,
    decode_announcement,
    decode_heartbeat,
    encode_announcement,
    encode_heartbeat,
)


def test_announcement_round_trip() -> None:
    source = build_receiver_announcement(module_id="receiver-1")
    decoded = decode_announcement(encode_announcement(source))

    assert decoded.module_id == "receiver-1"
    assert decoded.kind is ModuleKind.RECEIVER
    assert "video.rx" in decoded.capabilities


def test_heartbeat_round_trip() -> None:
    source = build_receiver_heartbeat(module_id="receiver-1")
    decoded = decode_heartbeat(encode_heartbeat(source))

    assert decoded.module_id == "receiver-1"


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


def test_heartbeat_recovers_module() -> None:
    station = StationCore()
    server = DiscoveryServer(station)
    address = ("127.0.0.1", 50000)

    hello = build_receiver_announcement(module_id="receiver-heartbeat")
    assert server.process_datagram(encode_announcement(hello), address).accepted is True

    time.sleep(0.02)
    station.check_stale_modules(timeout_seconds=0.001)
    module = station.registry.get("receiver-heartbeat")
    assert module is not None
    assert module.state is ModuleState.UNREACHABLE

    heartbeat = build_receiver_heartbeat(module_id="receiver-heartbeat")
    result = server.process_datagram(encode_heartbeat(heartbeat), address)

    assert result.accepted is True
    assert result.message_type == "module.heartbeat"
    assert module.state is ModuleState.READY
    assert station.journal.snapshot()[-1].code == "module.reconnected"


def test_unknown_heartbeat_is_rejected() -> None:
    station = StationCore()
    server = DiscoveryServer(station)
    heartbeat = build_receiver_heartbeat(module_id="missing")

    result = server.process_datagram(
        encode_heartbeat(heartbeat),
        ("127.0.0.1", 50000),
    )

    assert result.accepted is False
    assert result.error == "unknown module"


def test_repeated_hello_does_not_duplicate_ready_event() -> None:
    station = StationCore()
    server = DiscoveryServer(station)
    hello = build_receiver_announcement(module_id="receiver-repeat")
    payload = encode_announcement(hello)
    address = ("127.0.0.1", 50000)

    assert server.process_datagram(payload, address).accepted is True
    assert server.process_datagram(payload, address).accepted is True

    codes = [event.code for event in station.journal.snapshot()]
    assert codes.count("module.ready") == 1
