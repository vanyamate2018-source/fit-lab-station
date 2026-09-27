"""Small local hardware meter; never blocks on a subprocess or network request."""
import sys
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


def cpu_ticks():
    if sys.platform.startswith('linux'):
        values = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        return sum(values), values[3] + (values[4] if len(values) > 4 else 0)
    if sys.platform == 'darwin':
        import ctypes
        lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
        ticks = (ctypes.c_uint32 * 4)()
        count = ctypes.c_uint32(4)
        host = lib.mach_host_self()
        try:
            if lib.host_statistics(host, 3, ticks, ctypes.byref(count)) != 0:
                raise OSError('CPU statistics unavailable')
            return sum(ticks), ticks[2]
        finally:
            lib.mach_port_deallocate(ctypes.c_uint32.in_dll(lib, 'mach_task_self_').value, host)
    raise OSError('CPU statistics unavailable')


def temperature():
    values = []
    for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:
            kind = (zone / 'type').read_text().lower()
            if any(word in kind for word in ('cpu', 'soc', 'package')):
                value = float((zone / 'temp').read_text()) / 1000
                if -10 < value < 150:
                    values.append(value)
        except (OSError, ValueError):
            continue
    return max(values) if values else None


class SystemMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(142, 32)
        self.previous = None
        self.cpu = self.temp = None
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        try:
            current = cpu_ticks()
            if self.previous and current[0] > self.previous[0]:
                total = current[0] - self.previous[0]
                idle = current[1] - self.previous[1]
                self.cpu = max(0, min(100, 100 * (1 - idle / total)))
            self.previous = current
        except (OSError, ValueError, IndexError, AttributeError):
            self.cpu = None
        self.temp = temperature()
        t = f'{self.temp:.0f} °C' if self.temp is not None else 'датчик недоступен'
        c = f'{self.cpu:.0f} %' if self.cpu is not None else 'нет данных'
        self.setToolTip(f'Это устройство · температура: {t}\nЗагрузка процессора: {c}')
        self.setAccessibleName(f'Температура: {t}. Загрузка процессора: {c}')
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#494034'), 1))
        p.setBrush(QColor('#201f1c'))
        p.drawRoundedRect(QRectF(.5, .5, 141, 31), 8, 8)
        p.setPen(QPen(QColor('#efb768'), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(10, 7, 5, 13), 2.5, 2.5)
        p.drawEllipse(QRectF(8, 18, 9, 9))
        p.drawLine(12, 12, 12, 22)
        p.setPen(QPen(QColor('#494034'), 1))
        p.drawLine(72, 7, 72, 25)
        p.setPen(QPen(QColor('#efb768'), 1.3))
        p.drawRoundedRect(QRectF(81, 10, 12, 12), 2, 2)
        for n in (84, 90):
            p.drawLine(n, 7, n, 10)
            p.drawLine(n, 22, n, 25)
        font = p.font(); font.setPixelSize(12); font.setBold(True); p.setFont(font)
        p.setPen(QColor('#ff987a' if self.temp is not None and self.temp >= 80 else '#f4dfbf'))
        p.drawText(QRectF(23, 0, 46, 32), Qt.AlignmentFlag.AlignVCenter, f'{self.temp:.0f}°' if self.temp is not None else '—')
        p.setPen(QColor('#efb768' if self.cpu is not None and self.cpu >= 85 else '#e7e4de'))
        p.drawText(QRectF(99, 0, 40, 32), Qt.AlignmentFlag.AlignVCenter, f'{self.cpu:.0f}%' if self.cpu is not None else '—')
