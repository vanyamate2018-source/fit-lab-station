"""Local camera operation identity and cancellation; contains no wire protocol."""
from dataclasses import dataclass, field
from threading import Event
from time import monotonic
from uuid import uuid4


@dataclass
class CameraRequest:
    context: tuple
    label: str
    writing: bool = False
    operation: object = field(default=None, repr=False)
    credentials: object = field(default=None, repr=False)
    operation_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: float = field(default_factory=monotonic)
    started_at: float | None = None
    expires_at: float = field(default_factory=lambda: monotonic() + 15)
    cancel: Event = field(default_factory=Event, repr=False)
    terminal: bool = False

    def can_start(self, context):
        return not self.cancel.is_set() and self.context == context and monotonic() < self.expires_at
