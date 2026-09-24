from __future__ import annotations

from dataclasses import dataclass

from shared.models import ModuleInfo, ModuleKind, ModuleState
from shared.storage import StorageStatus


MODULE_TITLES = {
    ModuleKind.RECEIVER: "Модуль видеоприёма",
    ModuleKind.CONTROL: "Модуль управления",
    ModuleKind.SDR: "SDR-модуль",
}


STATE_TITLES = {
    ModuleState.UNREACHABLE: "нет связи",
    ModuleState.BOOTING: "загрузка",
    ModuleState.DISCOVERED: "обнаружен",
    ModuleState.AUTHENTICATING: "проверка",
    ModuleState.INCOMPATIBLE: "несовместим",
    ModuleState.READY: "готов",
    ModuleState.ACTIVE: "активен",
    ModuleState.WARNING: "предупреждение",
    ModuleState.ERROR: "ошибка",
    ModuleState.RECONNECTING: "переподключение",
    ModuleState.SHUTTING_DOWN: "завершение работы",
}


@dataclass(slots=True, frozen=True)
class ModuleStatusRow:
    kind: ModuleKind
    title: str
    state: str
    module_id: str | None


@dataclass(slots=True, frozen=True)
class MasterStatus:
    overall: str
    storage_ready: bool
    storage_root: str
    storage_free_gib: float
    connected_modules: int
    modules: tuple[ModuleStatusRow, ...]


def build_master_status(
    storage: StorageStatus,
    modules: list[ModuleInfo],
) -> MasterStatus:
    rows: list[ModuleStatusRow] = []

    for kind in (ModuleKind.RECEIVER, ModuleKind.CONTROL, ModuleKind.SDR):
        candidates = [module for module in modules if module.kind is kind]
        if not candidates:
            rows.append(
                ModuleStatusRow(
                    kind=kind,
                    title=MODULE_TITLES[kind],
                    state="не подключен",
                    module_id=None,
                )
            )
            continue

        module = candidates[0]
        rows.append(
            ModuleStatusRow(
                kind=kind,
                title=module.public_label(),
                state=STATE_TITLES[module.state],
                module_id=module.module_id,
            )
        )

    connected = sum(
        1
        for module in modules
        if module.state not in {ModuleState.UNREACHABLE, ModuleState.SHUTTING_DOWN}
    )

    overall = "ГОТОВ" if storage.writable else "ОГРАНИЧЕННЫЙ РЕЖИМ"

    return MasterStatus(
        overall=overall,
        storage_ready=storage.writable,
        storage_root=str(storage.root),
        storage_free_gib=storage.free_gib,
        connected_modules=connected,
        modules=tuple(rows),
    )


def render_text(status: MasterStatus) -> str:
    lines = [
        "FIT-LAB Station Master",
        f"Состояние: {status.overall}",
        "",
        f"Хранилище: {status.storage_root}",
        f"Запись: {'готова' if status.storage_ready else 'недоступна'}",
        f"Свободно: {status.storage_free_gib:.1f} GiB",
        "",
        f"Подключено модулей: {status.connected_modules}",
    ]

    for module in status.modules:
        lines.append(f"{module.title}: {module.state}")

    return "\n".join(lines)
