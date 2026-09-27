from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import timezone, datetime
UTC = timezone.utc
from shared.compat import StrEnum
from typing import Any


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class Event:
    timestamp: str
    severity: Severity
    source: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(
        cls,
        *,
        severity: Severity,
        source: str,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> "Event":
        return cls(
            timestamp=datetime.now(UTC).isoformat(),
            severity=severity,
            source=source,
            code=code,
            message=message,
            details=details or {},
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventJournal:
    def __init__(self, max_events: int = 1000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._events: deque[Event] = deque(maxlen=max_events)

    def append(self, event: Event) -> None:
        self._events.append(event)

    def snapshot(self) -> list[Event]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()
