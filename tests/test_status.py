from pathlib import Path

from master.status import build_master_status, render_text
from shared.models import ModuleInfo, ModuleKind, ModuleState
from shared.storage import StorageStatus


def make_storage(writable: bool = True) -> StorageStatus:
    return StorageStatus(
        root=Path("/tmp/fit-lab"),
        exists=True,
        writable=writable,
        total_bytes=256 * 1024**3,
        free_bytes=200 * 1024**3,
    )


def test_status_without_modules() -> None:
    status = build_master_status(make_storage(), [])

    assert status.overall == "ГОТОВ"
    assert status.connected_modules == 0
    assert all(row.state == "не подключен" for row in status.modules)


def test_status_with_receiver() -> None:
    receiver = ModuleInfo(
        module_id="receiver-1",
        kind=ModuleKind.RECEIVER,
        name="Модуль видеоприёма",
        protocol_version=1,
        state=ModuleState.ACTIVE,
    )

    status = build_master_status(make_storage(), [receiver])

    assert status.connected_modules == 1
    assert status.modules[0].state == "активен"
    assert status.modules[0].module_id == "receiver-1"


def test_status_warns_when_storage_is_not_writable() -> None:
    status = build_master_status(make_storage(writable=False), [])

    assert status.overall == "ОГРАНИЧЕННЫЙ РЕЖИМ"
    assert status.storage_ready is False


def test_text_renderer_is_human_readable() -> None:
    status = build_master_status(make_storage(), [])
    text = render_text(status)

    assert "FIT-LAB Station Master" in text
    assert "Подключено модулей: 0" in text
    assert "Модуль видеоприёма: не подключен" in text
