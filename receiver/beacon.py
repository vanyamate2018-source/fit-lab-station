from __future__ import annotations

import socket

from shared.models import ModuleKind
from shared.protocol import PROTOCOL_VERSION
from shared.wire import ModuleAnnouncement, encode_announcement


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


def send_announcement(
    host: str,
    port: int,
    announcement: ModuleAnnouncement,
) -> None:
    payload = encode_announcement(announcement)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(payload, (host, port))
