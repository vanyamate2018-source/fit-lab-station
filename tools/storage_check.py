from __future__ import annotations

from shared.config import StationConfig
from shared.storage import ensure_directories, probe_storage


def main() -> None:
    config = StationConfig.from_env()
    ensure_directories(config.data_root, config.required_directories())
    status = probe_storage(config.data_root)

    print(f"Хранилище: {status.root}")
    print(f"Доступно: {'да' if status.exists else 'нет'}")
    print(f"Запись: {'да' if status.writable else 'нет'}")
    print(f"Свободно: {status.free_gib:.1f} GiB")


if __name__ == "__main__":
    main()
