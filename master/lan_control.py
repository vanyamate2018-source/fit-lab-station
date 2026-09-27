"""Encrypted radio commands carried to the receiver through pinned SSH."""
import os
from pathlib import Path
import queue
import select
import struct
import subprocess
import threading
import time
from receiver.control_link import ControlLink


def write_frame(pipe, data, deadline, closed):
    """Bound a blocked bridge; never leave half a frame on a reused stream."""
    fd = pipe.fileno()
    view = memoryview(struct.pack('!H', len(data)) + data)
    while view:
        remaining = deadline - time.monotonic()
        if closed.is_set() or remaining <= 0:
            raise TimeoutError('Command bridge write expired')
        if not select.select([], [fd], [], min(.05, remaining))[1]:
            continue
        try:
            sent = os.write(fd, view)
        except BlockingIOError:
            continue
        if sent <= 0:
            raise BrokenPipeError('Command bridge closed')
        view = view[sent:]


class LanControl(ControlLink):
    def __init__(self, logs, key, root):
        self.bridge = None
        self.bridge_busy = False
        self.closed = threading.Event()
        self.frames = queue.Queue(maxsize=64)
        super().__init__(logs, key, aggregator_port=15652)
        self.command = ['ssh', '-T', '-i', str(Path(root)/'private/ssh/orangepi3b'),
                   '-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                   '-o','ConnectTimeout=3','-o','ServerAliveInterval=3','-o','ServerAliveCountMax=2',
                   'orangepi@'+os.environ.get('FIT_LAB_RECEIVER_HOST','192.168.2.36'),
                   'python3 /usr/local/libexec/fit-lab/command_bridge.py']
        if os.environ.get('FIT_LAB_EMBEDDED_RECEIVER') == '1':
            self.command = ['python3', '/usr/local/libexec/fit-lab/command_bridge.py']
        self.last_bridge = None
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.writer.start()

    def _write(self):
        retry = 1
        while not self.closed.is_set():
            process = None
            try:
                with (self.logs/'control-lan-ssh.log').open('ab') as log:
                    process = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                                               stdout=subprocess.DEVNULL, stderr=log, bufsize=0)
                os.set_blocking(process.stdin.fileno(), False)
                self.bridge = process
                began = time.monotonic()
                while not self.closed.is_set() and process.poll() is None:
                    if time.monotonic() - began >= .5:
                        self.bridge_busy = False
                    if time.monotonic() - began >= 5:
                        retry = 1
                    try: stamp, data = self.frames.get(timeout=.25)
                    except queue.Empty: continue
                    # Never replay a backlog of command frames after a LAN outage.
                    if time.monotonic()-stamp > 1:
                        self.state['tx_expired_frames'] = self.state.get('tx_expired_frames', 0) + 1
                        continue
                    write_frame(process.stdin, data, stamp + 1, self.closed)
            except TimeoutError:
                self.state['tx_bridge_stalls'] = self.state.get('tx_bridge_stalls', 0) + 1
            except (OSError, ValueError):
                pass
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                        try: process.wait(timeout=2)
                        except subprocess.TimeoutExpired: process.kill(); process.wait()
                    if process.returncode == 75:
                        self.bridge_busy = True
                    if process.stdin:
                        try: process.stdin.close()
                        except OSError: pass
                self.bridge = None
            if self.closed.wait(retry): break
            retry = min(8, retry*2)

    def poll(self, now):
        current = self.bridge
        if current is not self.last_bridge:
            self.last_bridge = current
            self.last_reply = 0
            self.pending.clear()
        result = super().poll(now)
        for _ in range(64):
            try: data, _ = self.encoded.recvfrom(4097)
            except BlockingIOError: break
            if 8 <= len(data) <= 4096:
                try: self.frames.put_nowait((now,data))
                except queue.Full: result['tx_queue_drops'] = result.get('tx_queue_drops',0)+1
        if self.bridge_busy:
            result.update(state='busy', error='Управление занято другой станцией')
        elif current is None or current.poll() is not None:
            result.update(state='retrying', error='Восстановление связи с видеомодулем')
        return result

    def close(self, stop_processes=True):
        self.closed.set()
        current = self.bridge
        if current is not None and current.poll() is None:
            current.terminate()
        writer = getattr(self, 'writer', None)
        if writer is not None: writer.join(timeout=3)
        super().close(stop_processes)
