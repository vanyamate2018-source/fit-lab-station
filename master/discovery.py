from __future__ import annotations

import socket
from dataclasses import dataclass

from master.core import StationCore
from shared.models import ModuleInfo
from shared.wire import ModuleAnnouncement, WireProtocolError, decode_announcement


@dataclass(slots=True, frozen=True)
class DiscoveryResult:
    accepted: bool
    address: tuple[str, int]
    module_id: str | None
    error: str | None = None


class DiscoveryServer:
    def __init__(self, station: StationCore) -> None:
        self.station = station

    def process_datagram(
        self,
        data: bytes,
        address: tuple[str, int],
    ) -> DiscoveryResult:
        try:
            announcement: ModuleAnnouncement = decode_announcement(data)
        except WireProtocolError as exc:
            return DiscoveryResult(
                accepted=False,
                address=address,
                module_id=None,
                error=str(exc),
            )

        module = ModuleInfo(
            module_id=announcement.module_id,
            kind=announcement.kind,
            name=announcement.name,
            protocol_version=announcement.protocol_version,
            capabilities=set(announcement.capabilities),
        )

        accepted = self.station.register_module(module)
        return DiscoveryResult(
            accepted=accepted,
            address=address,
            module_id=module.module_id if accepted else None,
            error=None if accepted else "module rejected",
        )

    def receive_once(
        self,
        sock: socket.socket,
        *,
        max_size: int = 65535,
    ) -> DiscoveryResult:
        data, address = sock.recvfrom(max_size)
        return self.process_datagram(data, address)
