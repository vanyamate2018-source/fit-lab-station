from __future__ import annotations

import time

from shared.models import ModuleInfo, ModuleState
from shared.protocol import PROTOCOL_VERSION


class ProtocolMismatchError(ValueError):
    pass


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, ModuleInfo] = {}

    def register(self, module: ModuleInfo) -> ModuleInfo:
        if module.protocol_version != PROTOCOL_VERSION:
            raise ProtocolMismatchError(
                f"protocol {module.protocol_version} is incompatible with {PROTOCOL_VERSION}"
            )
        module.last_seen_monotonic = time.monotonic()
        module.state = ModuleState.READY
        self._modules[module.module_id] = module
        return module

    def heartbeat(self, module_id: str) -> ModuleInfo:
        module = self._modules[module_id]
        module.last_seen_monotonic = time.monotonic()
        if module.state in {ModuleState.UNREACHABLE, ModuleState.RECONNECTING}:
            module.state = ModuleState.READY
        return module

    def mark_stale(self, timeout_seconds: float) -> list[ModuleInfo]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        now = time.monotonic()
        stale: list[ModuleInfo] = []
        for module in self._modules.values():
            if now - module.last_seen_monotonic > timeout_seconds:
                module.state = ModuleState.UNREACHABLE
                stale.append(module)
        return stale

    def get(self, module_id: str) -> ModuleInfo | None:
        return self._modules.get(module_id)

    def all(self) -> list[ModuleInfo]:
        return list(self._modules.values())
