from __future__ import annotations

import time
import uuid

from master.core import StationCore
from shared.models import ModuleInfo, ModuleKind
from shared.protocol import PROTOCOL_VERSION


def main() -> None:
    station = StationCore()
    receiver = ModuleInfo(
        module_id=str(uuid.uuid4()),
        kind=ModuleKind.RECEIVER,
        name="Модуль видеоприёма",
        protocol_version=PROTOCOL_VERSION,
        capabilities={"video.rx", "radio.rx1", "radio.rx2", "health"},
    )

    station.register_module(receiver)
    for _ in range(3):
        station.heartbeat(receiver.module_id)
        time.sleep(0.1)

    for event in station.journal.snapshot():
        print(f"[{event.severity}] {event.message}")


if __name__ == "__main__":
    main()
