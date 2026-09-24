from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(slots=True, frozen=True)
class StorageStatus:
    root: Path
    exists: bool
    writable: bool
    total_bytes: int
    free_bytes: int

    @property
    def free_gib(self) -> float:
        return self.free_bytes / (1024**3)


def ensure_directories(root: Path, directories: tuple[Path, ...]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for path in directories:
        path.mkdir(parents=True, exist_ok=True)


def probe_storage(root: Path) -> StorageStatus:
    exists = root.exists()
    writable = False
    total_bytes = 0
    free_bytes = 0

    if exists:
        try:
            usage = shutil.disk_usage(root)
            total_bytes = usage.total
            free_bytes = usage.free

            probe = root / ".fit-lab-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable = True
        except OSError:
            writable = False

    return StorageStatus(
        root=root,
        exists=exists,
        writable=writable,
        total_bytes=total_bytes,
        free_bytes=free_bytes,
    )
