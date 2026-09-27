"""Receiver-local observations written only by authenticated SSH sessions."""
import json
import time
from pathlib import Path

PRESENCE_DIR = Path('/mnt/fitlab-ssd/apps/fit-lab-receiver/master-presence')

def connected_masters(directory=PRESENCE_DIR, now=None, boot=None):
    now=time.monotonic() if now is None else now
    result=[]
    if boot is None:
        try:boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        except OSError:return result
    try:files=list(Path(directory).glob('*.json'))[:64]
    except OSError:return result
    for path in files:
        try:
            value=json.loads(path.read_text())
            age=now-float(value['seen'])
            if (0 <= age < 3.5 and value.get('authenticated') is True
                    and value.get('boot_id') == boot):result.append(value['address'])
        except (OSError,ValueError,KeyError,TypeError):continue
    return sorted(set(result))

class PresenceNotice:
    def __init__(self):
        self.ever=False;self.previous=False;self.lost=False
    def update(self,connected):
        if connected:
            restored=self.lost
            self.ever=True;self.previous=True;self.lost=False
            return 'restored' if restored else None
        if self.previous and self.ever:
            self.previous=False;self.lost=True;return 'lost'
        return None
