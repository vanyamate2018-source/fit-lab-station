"""Small, independently painted receiver instruments for the live view."""
import math
import time

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget, QLabel, QHBoxLayout, QVBoxLayout


class QualityField(QWidget):
    def __init__(self, caption, parent=None, compact=False):
        super().__init__(parent)
        column = QHBoxLayout(self) if compact else QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6 if compact else 1)
        title = QLabel(caption)
        title.setStyleSheet('color: #b4c2c1; font-size: 10px; background: transparent;')
        self.value = QLabel('—')
        self.value.setStyleSheet('color: #f6d39d; font-size: 14px; font-weight: 600; background: transparent;')
        column.addWidget(title)
        column.addWidget(self.value)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value):
        self.value.setText(value)


class LinkQuality(QWidget):
    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 0 if compact else 4, 9, 0 if compact else 3)
        row.setSpacing(12)
        self.fields = {}
        for key, title in (('snr', 'SNR · dB'), ('fec', 'FEC · пакеты'), ('loss', 'Потери')):
            field = QualityField(title, compact=compact)
            self.fields[key] = field
            row.addWidget(field, 1)
        self.fields['snr'].setToolTip('Лучший текущий SNR среди принимающих RX')
        self.fields['fec'].setToolTip('Пакеты, восстановленные FEC за сеанс')
        self.setFixedHeight(22 if compact else 40)

    def set_values(self, snr, fec, loss):
        for key, value in (('snr', snr), ('fec', fec), ('loss', loss)):
            self.fields[key].set_value(value)


class ReceiverIndicator(QWidget):
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.mode, self.rssi, self.snr = 'offline', None, None
        self.wide = False
        self.level = self.target_level = 0.0
        self.setMinimumWidth(138)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(58)
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._animate)
        self.set_signal('offline')

    def set_wide(self, wide):
        self.wide = wide
        self.setFixedHeight(74 if wide else 58)
        self.update()

    def set_signal(self, mode, rssi=None, snr=None):
        rssi = rssi if isinstance(rssi, (int, float)) and math.isfinite(rssi) else None
        snr = snr if isinstance(snr, (int, float)) and math.isfinite(snr) else None
        changed = (mode, rssi, snr) != (self.mode, self.rssi, self.snr)
        self.mode, self.rssi, self.snr = mode, rssi, snr
        self.target_level = sum(rssi >= t for t in (-90, -85, -80, -75, -70, -65, -60, -55)) if mode == 'receiving' and rssi is not None else 0
        if mode != 'receiving':
            self.level = 0  # Never leave stale green bars after signal loss.
        role = 'Вспомогательный · только приём' if self.name == 'RX3' else 'Приём · доступен для TX'
        value = f'{rssi:g} dBm' if mode == 'receiving' and rssi is not None else self.status_text()
        detail = f' · SNR {snr:g} dB' if mode == 'receiving' and snr is not None else ''
        self.setToolTip(f'{self.name} · {role}\n{value}{detail}\nКорректные пакеты объединяются в общий поток')
        self.setAccessibleName(f'{self.name}: {value}{detail}')
        self._sync_animation()
        if changed:
            self.update()

    def status_text(self):
        return {'receiving': 'Приём', 'ready': 'Готов', 'waiting': 'Ожидание',
                'initializing': 'Запуск', 'retrying': 'Поиск', 'disconnected': 'Нет связи',
                'offline': 'Не подключён'}.get(self.mode, 'Ожидание')

    def _sync_animation(self):
        if self.isVisible() and self.mode in ('receiving', 'initializing', 'retrying'):
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def _animate(self):
        self.level += (self.target_level - self.level) * .35
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_animation()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.mode == 'receiving'
        waiting = self.mode in ('ready', 'waiting', 'initializing', 'retrying')
        tint = QColor('#68e7ae' if active else '#f2bd72' if waiting else '#ee827d')
        pulse = .5 + .5 * math.sin(time.monotonic() * 2 * math.pi / 1.1)
        box = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        background = QLinearGradient(0, 0, self.width(), self.height())
        background.setColorAt(0, QColor('#242c2d'))
        background.setColorAt(1, QColor('#151c1f'))
        p.setBrush(background)
        p.setPen(QPen(QColor('#52605e' if active else '#404a4c'), 1))
        p.drawRoundedRect(box, 8, 8)
        # A quiet amber highlight ties the instruments to the Vector theme.
        p.setPen(QPen(QColor(255, 200, 126, 95 if active else 35), 1))
        p.drawLine(12, 1, min(self.width()-12, 43), 1)
        pad = 12 if self.wide else 9
        font = QFont(self.font())
        font.setPixelSize(13 if self.wide else 11)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, .7)
        p.setFont(font)
        p.setPen(QColor('#edc793'))
        p.drawText(QRectF(pad, 7, 36, 19), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.name)
        center = QRectF(pad+35, 12, 7, 7).center()
        glow = QRadialGradient(center, 8)
        halo = QColor(tint)
        halo.setAlpha(round(40 + 35*pulse) if active else 22)
        glow.setColorAt(0, halo)
        glow.setColorAt(1, QColor(tint.red(), tint.green(), tint.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(center, 8, 8)
        dot_color = QColor(tint)
        if active:
            dot_color.setAlpha(round(50 + 205 * pulse))
        p.setBrush(dot_color)
        p.drawEllipse(center, 2.7, 2.7)
        value = f'{self.rssi:g}' if active and self.rssi is not None else '—'
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
        font.setPixelSize(20 if self.wide else 17)
        p.setFont(font)
        p.setPen(QColor('#f4f3ed' if active else '#94a2a3'))
        p.drawText(QRectF(pad+46, 5, self.width()-2*pad-72, 24), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor('#b4c2c1'))
        p.drawText(QRectF(self.width()-pad-25, 9, 25, 19), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, 'dBm')
        bottom = self.height()-10
        if not active:
            p.setPen(tint)
            p.drawText(QRectF(pad, bottom-17, self.width()-2*pad, 17), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.status_text())
            return
        meter_width = self.width()-2*pad-53
        step = meter_width/8
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(8):
            height = 4 + i * (1.8 if self.wide else 1.35)
            strength = max(0, min(1, self.level-i))
            color = QColor('#f3bf75' if self.rssi is not None and self.rssi < -75 else '#68e7ae')
            base = QColor('#354144')
            p.setBrush(QColor(*(round(a+(b-a)*strength) for a,b in zip(
                (base.red(),base.green(),base.blue()),(color.red(),color.green(),color.blue())))))
            p.drawRoundedRect(QRectF(pad+i*step, bottom-height, max(2,step-3), height), 1.4, 1.4)
        p.setFont(font)
        p.setPen(QColor('#b4c2c1'))
        p.drawText(QRectF(self.width()-pad-50, bottom-16, 50, 17), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f'{self.snr:g} dB' if self.snr is not None else 'SNR —')
