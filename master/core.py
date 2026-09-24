from __future__ import annotations

from shared.events import Event, EventJournal, Severity
from shared.models import ModuleInfo, ModuleState
from shared.registry import ModuleRegistry, ProtocolMismatchError


class StationCore:
    def __init__(self) -> None:
        self.registry = ModuleRegistry()
        self.journal = EventJournal(max_events=1000)

    def register_module(self, module: ModuleInfo) -> bool:
        existing = self.registry.get(module.module_id)
        if existing is not None:
            if existing.kind is not module.kind:
                self.journal.append(
                    Event.now(
                        severity=Severity.ERROR,
                        source="master",
                        code="module.identity_conflict",
                        message=f"Конфликт идентификатора модуля: {module.public_label()}",
                        details={"module_id": module.module_id},
                    )
                )
                return False

            existing.name = module.name
            existing.capabilities = set(module.capabilities)
            existing.protocol_version = module.protocol_version
            try:
                if module.protocol_version != existing.protocol_version:
                    raise ProtocolMismatchError("protocol version changed")
                self.heartbeat(existing.module_id)
            except (ProtocolMismatchError, KeyError):
                return False
            return True

        try:
            self.registry.register(module)
        except ProtocolMismatchError as exc:
            self.journal.append(
                Event.now(
                    severity=Severity.ERROR,
                    source="master",
                    code="module.protocol_incompatible",
                    message=f"Несовместимая версия протокола: {module.public_label()}",
                    details={"module_id": module.module_id, "reason": str(exc)},
                )
            )
            return False

        self.journal.append(
            Event.now(
                severity=Severity.INFO,
                source="master",
                code="module.ready",
                message=f"Модуль готов: {module.public_label()}",
                details={
                    "module_id": module.module_id,
                    "kind": module.kind.value,
                    "capabilities": sorted(module.capabilities),
                },
            )
        )
        return True

    def heartbeat(self, module_id: str) -> bool:
        try:
            module, previous_state = self.registry.heartbeat(module_id)
        except KeyError:
            return False

        if previous_state in {ModuleState.UNREACHABLE, ModuleState.RECONNECTING}:
            self.journal.append(
                Event.now(
                    severity=Severity.INFO,
                    source="master",
                    code="module.reconnected",
                    message=f"Связь восстановлена: {module.public_label()}",
                    details={"module_id": module.module_id},
                )
            )
        return True

    def check_stale_modules(self, timeout_seconds: float = 5.0) -> None:
        for module in self.registry.mark_stale(timeout_seconds):
            self.journal.append(
                Event.now(
                    severity=Severity.WARNING,
                    source="master",
                    code="module.unreachable",
                    message=f"Связь с модулем потеряна: {module.public_label()}",
                    details={"module_id": module.module_id},
                )
            )
