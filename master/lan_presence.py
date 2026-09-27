"""Pinned SSH presence; retrying never runs on the UI or video thread."""
import subprocess
import threading
from pathlib import Path

class LanPresence:
    def __init__(self,root,host):
        self.closed=threading.Event();self.process=None
        self.root=root;self.host=host
        self.command=['ssh','-T','-i',str(Path(root)/'private/ssh/orangepi3b'),
                      '-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                      '-o','ConnectTimeout=3','-o','ServerAliveInterval=2','-o','ServerAliveCountMax=2',
                      'orangepi@'+host,'python3 /usr/local/libexec/fit-lab/command_bridge.py --presence']
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
    def run(self):
        retry=1
        while not self.closed.is_set():
            child=None
            try:
                child=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                self.process=child
                while child.poll() is None and not self.closed.is_set():
                    child.stdin.write(b'P\n');child.stdin.flush()
                    if self.closed.wait(1):break
                if child.returncode==0:retry=1
            except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired):pass
            finally:
                if child is not None:
                    if child.poll() is None:
                        child.terminate()
                        try:child.wait(2)
                        except subprocess.TimeoutExpired:child.kill();child.wait()
                    if child.stdin:
                        try:child.stdin.close()
                        except OSError:pass
                self.process=None
            if self.closed.wait(retry):break
            retry=min(5,retry*2)
    def close(self):
        self.closed.set()
        if self.process is not None and self.process.poll() is None:self.process.terminate()
        self.worker.join(3)
