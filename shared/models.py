from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ModuleKind(StrEnum):
    MASTER = "master"
    RECEIVER = "receiver"
    CONTROL = "control"
    SDR = "sdr"


class ModuleState(StrEnum):
    UNREACHABLE = "unreachable"
    BOOTING = "booting"
    DISCOVERED = "discovered"
    AUTHENTICATING = "authenticating"
    INCOMPATIBLE = "incompatible"
    READY = "ready"
    ACTIVE = "active"
    WARNING = "warning"
    ERROR = "error"
    RECONNECTING = "reconnecting"
    SHUTTING_DOWN = "shutting_down"


@dataclass(slots=True)
class ModuleInfo:
    module_id: str
    kind: ModuleKind
    name: str
    protocol_version: int
    capabilities: set[str] = field(default_factory=set)
    state: ModuleState = ModuleState.DISCOVERED
    last_seen_monotonic: float = 0.0

    def public_label(self) -> str:
        return self.name.strip() or self.kind.value
