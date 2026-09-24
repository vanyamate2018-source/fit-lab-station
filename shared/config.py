from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ENV_DATA_ROOT = "FIT_LAB_DATA_ROOT"


@dataclass(slots=True, frozen=True)
class StationConfig:
    data_root: Path

    @classmethod
    def from_env(cls) -> "StationConfig":
        raw = os.environ.get(ENV_DATA_ROOT, "").strip()
        if raw:
            return cls(data_root=Path(raw).expanduser())
        return cls(data_root=Path.cwd() / "data")

    def required_directories(self) -> tuple[Path, ...]:
        names = (
            "recordings",
            "telemetry",
            "logs",
            "iq",
            "backups",
            "exports",
            "temp",
        )
        return tuple(self.data_root / name for name in names)
