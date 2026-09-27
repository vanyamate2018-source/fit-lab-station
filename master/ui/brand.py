from pathlib import Path
import math
import re
from functools import lru_cache

from PySide6.QtCore import QSize, QRect, QRectF, QPointF, Qt, QTimer, QElapsedTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QPen, QLinearGradient
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtSvg import QSvgRenderer

ASSET = Path(__file__).resolve().parents[1] / "assets" / "fit-lab.svg"


@lru_cache(maxsize=64)
def ui_icon(name):
    source = ASSET.with_name(f"{name}.svg")
    if not source.exists():
        return QIcon()
    result = QIcon()
    for state, color in ((QIcon.State.Off, "#f0ede7"), (QIcon.State.On, "#ffbf65")):
        if name == "record":
            color = "#ff514b"
        svg = re.sub(r'#[0-9a-fA-F]{6}', color, source.read_text())
        renderer = QSvgRenderer(svg.encode())
        for size in (24, 32, 48, 64, 96):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            result.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return result


def icon() -> QIcon:
    generated = ASSET.with_name("app-icon.png")
    return QIcon(str(generated if generated.exists() else ASSET))


def splash_pixmap() -> QPixmap:
    generated = ASSET.with_name("vector-splash.png")
    if generated.exists():
        screen = next((s for s in QApplication.screens() if "MPI7009" not in s.name()), QApplication.primaryScreen())
        size = screen.geometry().size() if screen else QSize(1280, 720)
        dpr = screen.devicePixelRatio() if screen else 1
        source = QPixmap(str(generated))
        art = source.scaled(round(size.width()*dpr), round(size.height()*dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        result = art.copy((art.width()-round(size.width()*dpr))//2, (art.height()-round(size.height()*dpr))//2, round(size.width()*dpr), round(size.height()*dpr))
        result.setDevicePixelRatio(dpr)
        return result
    pixmap = QPixmap(580, 340)
    pixmap.fill(QColor("#131311"))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    icon().paint(p, QRect(240, 52, 100, 100))
    p.setPen(QColor("#efcc99"))
    p.setFont(QFont("Arial", 30, QFont.Weight.Bold))
    p.drawText(QRect(0, 175, 580, 50), Qt.AlignmentFlag.AlignCenter, "FIT-LAB")
    p.setPen(QColor("#a39888"))
    p.setFont(QFont("Arial", 11))
    p.drawText(QRect(0, 230, 580, 30), Qt.AlignmentFlag.AlignCenter, "GROUND STATION")
    p.end()
    return pixmap


class StartupSplash(QSplashScreen):
    def __init__(self):
        super().__init__(splash_pixmap())
        self.progress = 0
        self.display_progress = 0.0
        self.caption = "Запуск"
        self.clock = QElapsedTimer()
        self.clock.start()
        self.last_tick = 0
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation = QTimer(self)
        self.animation.setTimerType(Qt.TimerType.PreciseTimer)
        self.animation.timeout.connect(self._animate)
        self.animation.start(33)

    def _animate(self):
        elapsed = self.clock.elapsed()
        delta = max(0, elapsed - self.last_tick) / 1000
        self.last_tick = elapsed
        self.display_progress += (self.progress - self.display_progress) * (1 - math.exp(-delta * 3.5))
        if abs(self.progress - self.display_progress) < .15:
            self.display_progress = float(self.progress)
        self.update()

    def stage(self, value, caption):
        self.progress = max(self.progress, min(100, max(0, value)))
        self.caption = caption
        self.repaint()

    def finish_animated(self, window):
        self.display_progress = 100.0
        if QApplication.platformName() == 'xcb':
            # The receiver runs without a compositor for low-latency XVideo.
            # Window-opacity fades are unsupported there; retain the animated
            # progress for the final 240 ms, then reveal the prepared window.
            QTimer.singleShot(240, lambda: self.finish(window))
            return
        self.fade.setDuration(240)
        self.fade.setStartValue(1.0)
        self.fade.setEndValue(0.0)
        self.fade.finished.connect(lambda: self.finish(window))
        self.fade.start()

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    def drawContents(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        seconds = self.clock.elapsed() / 1000
        center = QPointF(self.width() * .5, self.height() * .36)
        # Only the splash animates these arcs. The live video has no effects.
        for radius, speed, offset in ((self.width() * .185, 24, 0), (self.width() * .236, -17, 155)):
            angle = (seconds * speed + offset) % 360
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(246, 187, 103, 125), 1.2))
            painter.drawArc(QRectF(center.x()-radius, center.y()-radius, radius*2, radius*2), int(angle*16), 30*16)
            point = center + QPointF(math.cos(math.radians(angle)) * radius, -math.sin(math.radians(angle)) * radius)
            painter.setPen(Qt.PenStyle.NoPen)
            for size, alpha in ((10, 10), (6, 24), (2.5, 220)):
                painter.setBrush(QColor(255, 204, 131, alpha))
                painter.drawEllipse(point, size, size)
        x, y, width = self.width() * .16, self.height() * .82, self.width() * .68
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#353129"))
        painter.drawRoundedRect(QRectF(x, y, width, 3), 1.5, 1.5)
        filled = width * self.display_progress / 100
        gradient = QLinearGradient(x, y, x + width, y)
        gradient.setColorAt(0, QColor("#9e7646"))
        gradient.setColorAt(1, QColor("#ffd18a"))
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(x, y, filled, 3), 1.5, 1.5)
        if filled > 2:
            painter.setBrush(QColor(255, 200, 125, 25))
            painter.drawEllipse(QPointF(x + filled, y + 1.5), 9, 5)
        painter.setPen(QColor("#cec2b1"))
        font = QFont("Arial")
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(QRectF(x, y + 16, width - 50, 24), Qt.AlignmentFlag.AlignLeft, self.caption)
        painter.setPen(QColor("#f1bf77"))
        painter.drawText(QRectF(x, y + 16, width, 24), Qt.AlignmentFlag.AlignRight, f"{round(self.display_progress)}%")
