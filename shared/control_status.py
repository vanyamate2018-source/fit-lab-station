"""Ephemeral control status is valid only within its receiver boot session."""
import json
from pathlib import Path
import time


def boot_identity():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def fresh_status(value, now, boot):
    try:
        age = now - float(value.get('updated', -1))
        return value.get('boot_id') == boot and 0 <= age < 3
    except (TypeError, ValueError):
        return False


if __name__ == '__main__':
    import sys
    path = Path(sys.argv[1])
    boot = boot_identity()
    while True:
        try:
            value = json.loads(path.read_text())
            value['fresh'] = fresh_status(value, time.monotonic(), boot)
            print(json.dumps(value), flush=True)
        except (OSError, ValueError):
            print('{}', flush=True)
        time.sleep(1)
