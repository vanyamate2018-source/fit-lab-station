from collections import deque
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class NativeVideoSurface(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEngine(self):
        return None

    def paintEvent(self, event):
        pass


class ActivityDot(QWidget):
    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.compact = compact
        self.setFixedSize(22 if compact else 94, 30)
        self.active = False
        self.mode = "offline"
        self.rssi = None
        self.tick = 0
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._animate)

    def set_active(self, active):
        self.set_signal("receiving" if active else "offline")

    def set_signal(self, mode, rssi=None):
        if (self.mode, self.rssi) == (mode, rssi):
            return
        self.mode, self.rssi = mode, rssi
        self.active = mode == "receiving"
        if mode in ("receiving", "initializing", "retrying") and self.isVisible():
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.mode in ("receiving", "initializing", "retrying"):
            self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _animate(self):
        self.tick += 1
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        strength = (math.sin(time.monotonic() * 2 * math.pi / 2.5) + 1) / 2
        color = QColor("#65e5a3" if self.active else "#f0c47d" if self.mode in
                       ("initializing", "retrying", "ready", "waiting") else "#ff776e")
        level = sum(self.rssi >= threshold for threshold in (-90, -85, -80, -75, -70, -65, -60, -55)) if isinstance(self.rssi, (int, float)) else 0
        p.setPen(Qt.PenStyle.NoPen)
        step = (self.width()-16)/8
        for i in range(0 if self.compact else 8):
            lit = self.active and i < level
            bar = QColor(color if lit or self.mode in ("initializing", "retrying") else "#41494a")
            if lit or self.mode in ("initializing", "retrying"):
                bar.setAlpha(int(215 + 40 * strength))
            p.setBrush(bar)
            height = 6 + i * 2.7
            p.drawRoundedRect(QRectF(16 + i * step, 28 - height, max(1, step * .65), height), .5, .5)
        halo = QColor(color)
        halo.setAlpha(int(25 + 30 * strength) if self.active else 22)
        p.setBrush(halo)
        p.drawEllipse(QRectF(2, 19, 11, 11))
        p.setBrush(color)
        p.drawEllipse(QRectF(4, 21, 7, 7))


class VideoCanvas(QWidget):
    doubleClicked = Signal()
    nativeResized = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.native_surface = None
        self.native_active = False
        self.native_settle = QTimer(self)
        self.native_settle.setSingleShot(True)
        self.native_settle.setInterval(120)
        self.native_settle.timeout.connect(self._present_native)
        self.title = "Готов к приёму"
        self.subtitle = "Подключите приёмник"
        self.stale = False
        self.frame_number = 0
        self.painted_number = 0
        self.painted_frames = 0
        self.paint_max_ms = 0.0
        self.performance_time = time.monotonic()
        self.setMinimumSize(320, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Isolate each video repaint from the translucent dashboard ancestry.
        # Otherwise the entire Retina window is composited for every frame.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        from master.ui.audio_controls import AudioControls
        self.audio_controls = AudioControls(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.native_surface is not None:
            self._fit_native_surface()
        self.audio_controls.setFixedWidth(min(340, max(240, self.width() - 32)))
        self.audio_controls.move(16, max(8, self.height() - self.audio_controls.height() - 16))

    def _fit_native_surface(self):
        # XVideo owns only the image rectangle. Qt must paint the surrounding
        # space; an unpainted native border otherwise retains old page pixels.
        width = min(self.width(), round(self.height() * 16 / 9))
        height = min(self.height(), round(width * 9 / 16))
        self.native_surface.hide()
        self.native_surface.setGeometry((self.width()-width)//2, (self.height()-height)//2, width, height)
        self.nativeResized.emit(width, height)
        self.native_settle.start()
        self.update()

    def set_native_active(self, active):
        self.native_active = active
        self._present_native()

    def settle_native(self):
        if self.native_surface is not None:
            self.native_surface.hide()
            self.native_settle.start()
            self.update()

    def _present_native(self):
        if self.native_surface is not None:
            self.native_surface.setVisible(self.native_active and not self.native_settle.isActive()
                                           and not self.window().isMinimized() and self.isVisible())

    def native_handle(self):
        if self.native_surface is None:
            self.native_surface = NativeVideoSurface(self)
            self._fit_native_surface()
            self.native_surface.hide()
            self.audio_controls.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            self.audio_controls.raise_()
        return int(self.native_surface.winId())

    def mouseMoveEvent(self, event):
        self.audio_controls.reveal()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        self.audio_controls.reveal()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.audio_controls.reveal()
        super().enterEvent(event)

    def set_frame(self, image):
        self.image = image
        self.frame_number += 1
        self.update()

    def performance(self):
        now = time.monotonic()
        elapsed = max(.001, now - self.performance_time)
        result = {'presented_fps': round(self.painted_frames / elapsed, 1),
                  'paint_max_ms': round(self.paint_max_ms, 2)}
        self.painted_frames = 0
        self.paint_max_ms = 0.0
        self.performance_time = now
        return result

    def showEvent(self, event):
        # Time spent on a settings page is not a slow video-display interval.
        self.performance()
        super().showEvent(event)
        self.settle_native()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()

    def paintEvent(self, _):
        started = time.monotonic()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#151a1b'))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        clip = QPainterPath()
        clip.addRoundedRect(area, 5, 5)
        painter.setClipPath(clip)
        painter.fillRect(area, QColor("#0a1012"))
        if self.native_surface is not None and self.native_active:
            painter.end()
            return
        if not self.image.isNull() and not self.stale:
            size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                            size.width(), size.height())
            painter.drawImage(target, self.image)
            if self.painted_number != self.frame_number:
                self.painted_number = self.frame_number
                self.painted_frames += 1
        else:
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, QColor("#263437"))
            gradient.setColorAt(1, QColor("#111b1e"))
            painter.fillRect(area, gradient)
            painter.setPen(QPen(QColor(107, 146, 154, 18), 1))
            for x in range(0, self.width(), 64):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), 64):
                painter.drawLine(0, y, self.width(), y)
            radius = min(76, max(24, (self.height() - 85) * .28))
            center = QPointF(self.width() / 2, (self.height() - 55) / 2 - radius * .3)
            painter.setPen(QPen(QColor("#575244"), 1))
            for scale in (.4, .68, 1.0):
                painter.drawEllipse(center, radius * scale, radius * scale)
            painter.setPen(QPen(QColor("#edbc79"), 2))
            painter.drawLine(center + QPointF(-13, 0), center + QPointF(13, 0))
            painter.drawLine(center + QPointF(0, -13), center + QPointF(0, 13))
            painter.setPen(QColor("#eee9da"))
            painter.setFont(QFont("Arial", 14 if self.height() < 250 else 18, QFont.Weight.DemiBold))
            painter.drawText(QRectF(10, center.y() + radius + 10, self.width() - 20, 28), Qt.AlignmentFlag.AlignCenter, self.title)
            painter.setFont(QFont("Arial", 11))
            painter.setPen(QColor("#b1ada3"))
            painter.drawText(QRectF(10, center.y() + radius + 42, self.width() - 20, 24), Qt.AlignmentFlag.AlignCenter, self.subtitle)
        painter.setClipping(False)
        painter.setPen(QPen(QColor("#84775d"), 1))
        painter.drawRoundedRect(area, 5, 5)
        painter.end()
        self.paint_max_ms = max(self.paint_max_ms, (time.monotonic() - started) * 1000)


class TrafficChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = deque([0.0] * 60, maxlen=60)
        self.setMinimumHeight(80)

    def append(self, value):
        self.values.append(value)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#394231"), 1))
        for y in (10, self.height() // 2, self.height() - 10):
            p.drawLine(0, y, self.width(), y)
        maximum = max(1, max(self.values) * 1.2)
        path = QPainterPath()
        for i, value in enumerate(self.values):
            point = QPointF(i * self.width() / 59, self.height() - 10 - value / maximum * (self.height() - 20))
            path.moveTo(point) if i == 0 else path.lineTo(point)
        p.setPen(QPen(QColor("#f2be74"), 2))
        p.drawPath(path)
