from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


ENV_DATA_ROOT = "FIT_LAB_DATA_ROOT"
ENV_CONFIG_PATH = "FIT_LAB_CONFIG"


def default_data_root() -> Path:
    raw = os.environ.get(ENV_DATA_ROOT, "").strip()
    if raw:
        return Path(raw).expanduser()
    ssd = Path("/Volumes/FIT-LAB")
    return ssd / "data" if ssd.is_mount() else Path.cwd() / "data"


def default_config_path() -> Path:
    raw = os.environ.get(ENV_CONFIG_PATH, "").strip()
    if raw:
        return Path(raw).expanduser()
    return default_data_root() / "config" / "station.json"


@dataclass(slots=True, frozen=True)
class StationConfig:
    data_root: Path

    @classmethod
    def load(cls) -> "StationConfig":
        env_root = os.environ.get(ENV_DATA_ROOT, "").strip()
        if env_root:
            return cls(data_root=Path(env_root).expanduser())

        path = default_config_path()
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_root = str(payload.get("data_root", "")).strip()
            if raw_root:
                return cls(data_root=Path(raw_root).expanduser())

        return cls(data_root=default_data_root())

    @classmethod
    def from_env(cls) -> "StationConfig":
        return cls.load()

    def required_directories(self) -> tuple[Path, ...]:
        names = (
            "recordings",
            "telemetry",
            "logs",
            "iq",
            "backups",
            "exports",
            "temp",
            "config",
            "cache",
        )
        return tuple(self.data_root / name for name in names)


def save_local_config(config: StationConfig, path: Path | None = None) -> Path:
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"data_root": str(config.data_root)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target
