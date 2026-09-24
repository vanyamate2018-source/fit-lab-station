from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from shared.models import ModuleKind
from shared.protocol import PROTOCOL_NAME, PROTOCOL_VERSION


class WireProtocolError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class ModuleAnnouncement:
    module_id: str
    kind: ModuleKind
    name: str
    protocol_version: int
    capabilities: tuple[str, ...]


def encode_announcement(message: ModuleAnnouncement) -> bytes:
    payload = {
        "protocol": PROTOCOL_NAME,
        "version": message.protocol_version,
        "type": "module.hello",
        "module": {
            "id": message.module_id,
            "kind": message.kind.value,
            "name": message.name,
            "capabilities": list(message.capabilities),
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def decode_announcement(data: bytes) -> ModuleAnnouncement:
    try:
        payload: dict[str, Any] = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WireProtocolError("invalid JSON packet") from exc

    if payload.get("protocol") != PROTOCOL_NAME:
        raise WireProtocolError("unknown protocol")
    if payload.get("type") != "module.hello":
        raise WireProtocolError("unsupported message type")

    version = payload.get("version")
    if not isinstance(version, int):
        raise WireProtocolError("invalid protocol version")

    module = payload.get("module")
    if not isinstance(module, dict):
        raise WireProtocolError("missing module payload")

    module_id = module.get("id")
    name = module.get("name")
    kind_raw = module.get("kind")
    capabilities_raw = module.get("capabilities", [])

    if not isinstance(module_id, str) or not module_id.strip():
        raise WireProtocolError("invalid module id")
    if not isinstance(name, str):
        raise WireProtocolError("invalid module name")
    if not isinstance(capabilities_raw, list) or not all(
        isinstance(item, str) for item in capabilities_raw
    ):
        raise WireProtocolError("invalid capabilities")

    try:
        kind = ModuleKind(kind_raw)
    except ValueError as exc:
        raise WireProtocolError("unknown module kind") from exc

    return ModuleAnnouncement(
        module_id=module_id,
        kind=kind,
        name=name,
        protocol_version=version,
        capabilities=tuple(capabilities_raw),
    )


def current_protocol_version() -> int:
    return PROTOCOL_VERSION
