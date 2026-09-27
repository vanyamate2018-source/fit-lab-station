import socket
import threading
import time
import json
import pytest

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
    assert module.state is ModuleState.DISCOVERED
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


def test_repeated_hello_does_not_duplicate_discovered_event() -> None:
    station = StationCore()
    server = DiscoveryServer(station)
    hello = build_receiver_announcement(module_id="receiver-repeat")
    payload = encode_announcement(hello)
    address = ("127.0.0.1", 50000)

    assert server.process_datagram(payload, address).accepted is True
    assert server.process_datagram(payload, address).accepted is True

    codes = [event.code for event in station.journal.snapshot()]
    assert codes.count("module.discovered") == 1


def test_discovery_records_observed_address_without_marking_ready():
    station = StationCore()
    server = DiscoveryServer(station)
    hello = build_receiver_announcement(module_id='receiver-address')
    server.process_datagram(encode_announcement(hello), ('192.168.2.20', 60400))
    module = station.registry.get('receiver-address')
    assert module.address == '192.168.2.20'
    assert module.state is ModuleState.DISCOVERED


@pytest.mark.parametrize('change', [{'version': True}, {'module': {'id': 'x', 'name': 'x' * 129, 'kind': 'receiver'}}, {'padding': 'x' * 8192}])
def test_unbounded_or_malformed_announcements_are_rejected(change):
    message = json.loads(encode_announcement(build_receiver_announcement(module_id='test')))
    message.update(change)
    result = DiscoveryServer(StationCore()).process_datagram(json.dumps(message).encode(), ('127.0.0.1', 1))
    assert not result.accepted


def test_discovery_inventory_is_bounded_and_existing_modules_can_reconnect():
    station = StationCore()
    server = DiscoveryServer(station)
    for index in range(33):
        hello = build_receiver_announcement(module_id=f'rx-{index}')
        result = server.process_datagram(encode_announcement(hello), ('127.0.0.1', 60400))
        assert result.accepted is (index < 32)
    assert len(station.registry.all()) == 32
    hello = build_receiver_announcement(module_id='rx-0')
    assert server.process_datagram(encode_announcement(hello), ('127.0.0.1', 60400)).accepted
