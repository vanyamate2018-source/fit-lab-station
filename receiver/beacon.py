from __future__ import annotations

import socket

from shared.models import ModuleKind
from shared.protocol import PROTOCOL_VERSION
from shared.wire import (
    ModuleAnnouncement,
    ModuleHeartbeat,
    encode_announcement,
    encode_heartbeat,
)


def build_receiver_announcement(
    *,
    module_id: str,
    name: str = "Модуль видеоприёма",
) -> ModuleAnnouncement:
    return ModuleAnnouncement(
        module_id=module_id,
        kind=ModuleKind.RECEIVER,
        name=name,
        protocol_version=PROTOCOL_VERSION,
        capabilities=("video.rx", "radio.rx1", "radio.rx2", "health"),
    )


def build_receiver_heartbeat(*, module_id: str) -> ModuleHeartbeat:
    return ModuleHeartbeat(
        module_id=module_id,
        protocol_version=PROTOCOL_VERSION,
    )


def send_announcement(
    host: str,
    port: int,
    announcement: ModuleAnnouncement,
) -> None:
    _send_datagram(host, port, encode_announcement(announcement))


def send_heartbeat(
    host: str,
    port: int,
    heartbeat: ModuleHeartbeat,
) -> None:
    _send_datagram(host, port, encode_heartbeat(heartbeat))


def _send_datagram(host: str, port: int, payload: bytes) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(payload, (host, port))
