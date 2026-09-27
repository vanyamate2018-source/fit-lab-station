"""Reuse the receiver's radio control service through an authenticated SSH tunnel."""
import json
import subprocess
import threading
import time
from pathlib import Path


class RemoteControl:
    def __init__(self, root, host):
        self.closed=threading.Event()
        self.state={'state':'starting'}
        self.seen=0
        self.child=None
        self.command=['ssh','-T','-i',str(Path(root)/'private/ssh/orangepi3b'),
                      '-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                      '-o','ConnectTimeout=3','-o','ExitOnForwardFailure=yes',
                      '-o','ServerAliveInterval=2','-o','ServerAliveCountMax=2',
                      '-L','127.0.0.1:19022:127.0.0.1:19022','orangepi@'+host,
                      'PYTHONPATH=/mnt/fitlab-ssd/apps/fit-lab-station/source python3 -u -m shared.control_status /mnt/fitlab-ssd/apps/fit-lab-station/data/logs/control-live.json']
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
    def run(self):
        while not self.closed.is_set():
            try:
                self.child=subprocess.Popen(self.command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                for line in self.child.stdout:
                    try:
                        value=json.loads(line)
                        if value.pop('fresh',False):
                            self.state=value;self.seen=time.monotonic()
                    except (ValueError,TypeError): pass
                    if self.closed.is_set():break
            except OSError:pass
            finally:
                if self.child and self.child.poll() is None:
                    self.child.terminate()
                    try:self.child.wait(2)
                    except subprocess.TimeoutExpired:self.child.kill();self.child.wait()
            if self.closed.wait(2):break
    def poll(self, now):
        if now-self.seen >=3:return {'state':'retrying'}
        value=dict(self.state)
        if value.get('state')=='connected':value['last_reply_monotonic']=now
        return value
    def close(self, **kwargs):
        self.closed.set()
        if self.child and self.child.poll() is None:self.child.terminate()
        self.worker.join(3)
