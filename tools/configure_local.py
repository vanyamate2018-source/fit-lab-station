from __future__ import annotations

import argparse
from pathlib import Path

from shared.config import StationConfig, save_local_config
from shared.storage import ensure_directories, probe_storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Настройка локального хранилища FIT-LAB Station"
    )
    parser.add_argument(
        "data_root",
        type=Path,
        help="Путь к каталогу данных FIT-LAB",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = StationConfig(data_root=args.data_root.expanduser())
    ensure_directories(config.data_root, config.required_directories())
    status = probe_storage(config.data_root)

    if not status.writable:
        raise SystemExit(f"Хранилище недоступно для записи: {config.data_root}")

    config_path = save_local_config(config)

    print(f"Конфигурация сохранена: {config_path}")
    print(f"Хранилище: {config.data_root}")
    print(f"Свободно: {status.free_gib:.1f} GiB")


if __name__ == "__main__":
    main()
