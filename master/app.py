from __future__ import annotations

from master.core import StationCore
from master.status import build_master_status, render_text
from shared.config import StationConfig
from shared.storage import ensure_directories, probe_storage


def main() -> None:
    config = StationConfig.load()
    ensure_directories(config.data_root, config.required_directories())

    storage = probe_storage(config.data_root)
    station = StationCore()
    status = build_master_status(storage, station.registry.all())

    print(render_text(status))


if __name__ == "__main__":
    main()
