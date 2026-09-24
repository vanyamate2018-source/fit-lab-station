from master.core import StationCore
from shared.models import ModuleInfo, ModuleKind, ModuleState
from shared.protocol import PROTOCOL_VERSION


def test_receiver_registration() -> None:
    station = StationCore()
    module = ModuleInfo(
        module_id="receiver-test",
        kind=ModuleKind.RECEIVER,
        name="Модуль видеоприёма",
        protocol_version=PROTOCOL_VERSION,
        capabilities={"video.rx", "radio.rx1", "radio.rx2"},
    )

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
