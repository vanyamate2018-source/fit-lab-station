"""Small compatibility layer for supported Python 3.10 systems."""
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):
        def __str__(self):
            return self.value
