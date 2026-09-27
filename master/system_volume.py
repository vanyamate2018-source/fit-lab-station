"""Debounced system volume for receiver appliances; no shell or GUI blocking."""
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, QTimer, Signal


def pactl(*args):
    return subprocess.run(['pactl', *args], check=True, capture_output=True, text=True,
                          timeout=2, env={**os.environ, 'LC_ALL': 'C'}).stdout


def read_volume():
    volumes = [int(value) for value in re.findall(r'(\d+)%', pactl('get-sink-volume', '@DEFAULT_SINK@'))]
    if not volumes:
        raise RuntimeError('Не удалось прочитать громкость')
    muted = pactl('get-sink-mute', '@DEFAULT_SINK@').strip().endswith('yes')
    return min(100, round(sum(volumes)/len(volumes))), muted


def apply_volume(value):
    percent, muted = value
    pactl('set-sink-volume', '@DEFAULT_SINK@', f'{max(0,min(100,int(percent)))}%')
    pactl('set-sink-mute', '@DEFAULT_SINK@', '1' if muted else '0')
    return read_volume()


class SystemVolume(QObject):
    changed = Signal(int, bool)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fitlab-volume')
        self.future = None
        self.pending = None
        self.last = None
        self.last_poll = self.last_error = -100.0
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def set_volume(self, percent, muted):
        self.pending = (percent, muted)

    def tick(self):
        now = time.monotonic()
        if self.future is not None and self.future.done():
            try:
                value = self.future.result()
                if self.pending is None and value != self.last:
                    self.last = value
                    self.changed.emit(*value)
            except (OSError, subprocess.SubprocessError, RuntimeError):
                if now-self.last_error > 30:
                    self.error.emit('Системная громкость недоступна')
                    self.last_error = now
            self.future = None
        if self.future is None:
            if self.pending is not None:
                value, self.pending = self.pending, None
                self.future = self.pool.submit(apply_volume, value)
                self.last_poll = now
            elif now-self.last_poll >= 1.5:
                self.future = self.pool.submit(read_volume)
                self.last_poll = now

    def close(self):
        self.timer.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
