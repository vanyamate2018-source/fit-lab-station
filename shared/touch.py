"""MPI7009 / QDtech 0712:0009 report, as declared by its USB HID descriptor."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Contact:
    id: int
    x: float
    y: float


def decode_qdtech(report: bytes) -> list[Contact]:
    if len(report) != 56 or report[0] != 1:
        raise ValueError("Unsupported digitizer report")
    count = report[55]
    if count > 10:
        raise ValueError("Invalid contact count")
    contacts = []
    for offset in range(1, 1 + count * 5, 5):
        flags = report[offset]
        if not flags & 0x40:
            continue
        ident = flags & 0x3f
        x = int.from_bytes(report[offset+1:offset+3], "little")
        y = int.from_bytes(report[offset+3:offset+5], "little")
        if x > 1024 or y > 600 or any(p.id == ident for p in contacts):
            raise ValueError("Invalid contact coordinates or identity")
        contacts.append(Contact(ident, x / 1024, y / 600))
    # Slots beyond Contact Count contain stale/padding data on MPI7009.
    # Tip Switch, not the number of slots, tells us which fingers are down.
    return contacts if count else []
