import time

from master.core import StationCore
from shared.models import ModuleInfo, ModuleKind, ModuleState
from shared.protocol import PROTOCOL_VERSION


def make_receiver(module_id: str = "receiver-test") -> ModuleInfo:
    return ModuleInfo(
        module_id=module_id,
        kind=ModuleKind.RECEIVER,
        name="Модуль видеоприёма",
        protocol_version=PROTOCOL_VERSION,
        capabilities={"video.rx", "radio.rx1", "radio.rx2"},
    )


def test_receiver_registration() -> None:
    station = StationCore()
    module = make_receiver()

    assert station.register_module(module) is True
    assert station.registry.get("receiver-test") is module
    assert module.state is ModuleState.READY
    assert station.journal.snapshot()[-1].code == "module.ready"


def test_incompatible_module_is_rejected() -> None:
    station = StationCore()
    module = ModuleInfo(
        module_id="old-receiver",
        kind=ModuleKind.RECEIVER,
        name="Старый приёмник",
        protocol_version=PROTOCOL_VERSION + 1,
    )

    assert station.register_module(module) is False
    assert station.registry.get("old-receiver") is None
    assert station.journal.snapshot()[-1].code == "module.protocol_incompatible"


def test_timeout_is_logged_once_and_heartbeat_recovers_module() -> None:
    station = StationCore()
    module = make_receiver()
    station.register_module(module)

    time.sleep(0.02)
    station.check_stale_modules(timeout_seconds=0.001)
    station.check_stale_modules(timeout_seconds=0.001)

    codes = [event.code for event in station.journal.snapshot()]
    assert codes.count("module.unreachable") == 1
    assert module.state is ModuleState.UNREACHABLE

    station.heartbeat(module.module_id)

    assert module.state is ModuleState.READY
    assert station.journal.snapshot()[-1].code == "module.reconnected"
