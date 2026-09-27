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


@dataclass(slots=True, frozen=True)
class ModuleHeartbeat:
    module_id: str
    protocol_version: int


WireMessage = ModuleAnnouncement | ModuleHeartbeat


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _decode_payload(data: bytes) -> dict[str, Any]:
    if len(data) > 8192:
        raise WireProtocolError("packet too large")
    try:
        payload: dict[str, Any] = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WireProtocolError("invalid JSON packet") from exc

    if not isinstance(payload, dict):
        raise WireProtocolError("expected JSON object")
    if payload.get("protocol") != PROTOCOL_NAME:
        raise WireProtocolError("unknown protocol")

    version = payload.get("version")
    if type(version) is not int:
        raise WireProtocolError("invalid protocol version")

    return payload


def encode_announcement(message: ModuleAnnouncement) -> bytes:
    return _encode(
        {
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
    )


def encode_heartbeat(message: ModuleHeartbeat) -> bytes:
    return _encode(
        {
            "protocol": PROTOCOL_NAME,
            "version": message.protocol_version,
            "type": "module.heartbeat",
            "module_id": message.module_id,
        }
    )


def decode_message(data: bytes) -> WireMessage:
    payload = _decode_payload(data)
    message_type = payload.get("type")

    if message_type == "module.hello":
        return _decode_announcement_payload(payload)
    if message_type == "module.heartbeat":
        return _decode_heartbeat_payload(payload)

    raise WireProtocolError("unsupported message type")


def decode_announcement(data: bytes) -> ModuleAnnouncement:
    message = decode_message(data)
    if not isinstance(message, ModuleAnnouncement):
        raise WireProtocolError("expected module.hello")
    return message


def decode_heartbeat(data: bytes) -> ModuleHeartbeat:
    message = decode_message(data)
    if not isinstance(message, ModuleHeartbeat):
        raise WireProtocolError("expected module.heartbeat")
    return message


def _decode_announcement_payload(payload: dict[str, Any]) -> ModuleAnnouncement:
    version = payload["version"]
    module = payload.get("module")
    if not isinstance(module, dict):
        raise WireProtocolError("missing module payload")

    module_id = module.get("id")
    name = module.get("name")
    kind_raw = module.get("kind")
    capabilities_raw = module.get("capabilities", [])

    if not isinstance(module_id, str) or not module_id.strip() or len(module_id) > 128 or any(ord(c) < 32 for c in module_id):
        raise WireProtocolError("invalid module id")
    if not isinstance(name, str) or len(name) > 128 or any(ord(c) < 32 for c in name):
        raise WireProtocolError("invalid module name")
    if not isinstance(capabilities_raw, list) or len(capabilities_raw) > 64 or not all(
        isinstance(item, str) and len(item) <= 128 for item in capabilities_raw
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


def _decode_heartbeat_payload(payload: dict[str, Any]) -> ModuleHeartbeat:
    module_id = payload.get("module_id")
    if not isinstance(module_id, str) or not module_id.strip() or len(module_id) > 128:
        raise WireProtocolError("invalid module id")

    return ModuleHeartbeat(
        module_id=module_id,
        protocol_version=payload["version"],
    )


def current_protocol_version() -> int:
    return PROTOCOL_VERSION
