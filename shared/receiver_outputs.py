"""Independent destinations for the installed Linux receiver service."""
import json
import os
from pathlib import Path
import tempfile

DEFAULT_PATH = Path('/mnt/fitlab-ssd/apps/fit-lab-receiver/outputs.json')


def read(path=DEFAULT_PATH):
    try: value = json.loads(Path(path).read_text())
    except FileNotFoundError: value = {}
    return {key: value.get(key, default) is True for key, default in
            (('master_enabled', True), ('local_enabled', False))}


def update(path=DEFAULT_PATH, **changes):
    if set(changes)-{'master_enabled','local_enabled'} or any(type(v) is not bool for v in changes.values()):
        raise ValueError('Invalid output settings')
    path=Path(path)
    import fcntl
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value=read(path); value.update(changes)
        fd,name=tempfile.mkstemp(dir=path.parent,prefix='.outputs-')
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(value,stream); stream.flush(); os.fsync(stream.fileno())
            os.replace(name,path)
        finally:
            if os.path.exists(name):os.unlink(name)
    return value
