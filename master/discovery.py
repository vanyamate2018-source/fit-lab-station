from __future__ import annotations

import socket
from dataclasses import dataclass

from master.core import StationCore
from shared.models import ModuleInfo
from shared.wire import (
    ModuleAnnouncement,
    ModuleHeartbeat,
    WireProtocolError,
    decode_message,
)


@dataclass(slots=True, frozen=True)
class DiscoveryResult:
    accepted: bool
    address: tuple[str, int]
    module_id: str | None
    message_type: str | None = None
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
            message = decode_message(data)
        except WireProtocolError as exc:
            return DiscoveryResult(
                accepted=False,
                address=address,
                module_id=None,
                error=str(exc),
            )

        if isinstance(message, ModuleAnnouncement):
            module = ModuleInfo(
                module_id=message.module_id,
                kind=message.kind,
                name=message.name,
                protocol_version=message.protocol_version,
                capabilities=set(message.capabilities),
            )
            accepted = self.station.register_module(module)
            return DiscoveryResult(
                accepted=accepted,
                address=address,
                module_id=module.module_id if accepted else None,
                message_type="module.hello",
                error=None if accepted else "module rejected",
            )

        if isinstance(message, ModuleHeartbeat):
            accepted = self.station.heartbeat(message.module_id)
            return DiscoveryResult(
                accepted=accepted,
                address=address,
                module_id=message.module_id if accepted else None,
                message_type="module.heartbeat",
                error=None if accepted else "unknown module",
            )

        return DiscoveryResult(
            accepted=False,
            address=address,
            module_id=None,
            error="unsupported message",
        )

    def receive_once(
        self,
        sock: socket.socket,
        *,
        max_size: int = 65535,
    ) -> DiscoveryResult:
        data, address = sock.recvfrom(max_size)
        return self.process_datagram(data, address)
