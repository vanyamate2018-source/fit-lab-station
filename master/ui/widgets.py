from __future__ import annotations
import math
import time

from PySide6.QtCore import Qt, QObject, Property, QPropertyAnimation, QEasingCurve, QRectF, QTimer, QEvent
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QLinearGradient, QRadialGradient, QIcon
from master.ui.brand import ui_icon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class ElidingLabel(QLabel):
    """Keep notifications on one line; retain the complete text for accessibility."""
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.full_text = str(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setText(text)

    def setText(self, text):
        self.full_text = str(text)
        self.setAccessibleName(self.full_text)
        self.setToolTip(self.full_text)
        self._fit_text()

    def _fit_text(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight,
                                                     max(0, self.contentsRect().width() - 20)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()


class InteractionHalo(QObject):
    """Local focus animation; never capture the video surface."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner, self._value = owner, 0.0
        self.animation = QPropertyAnimation(self, b"value", self)
        self.animation.setDuration(120)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_value(self):
        return self._value

    def set_value(self, value):
        self._value = value
        self.owner.update()

    value = Property(float, get_value, set_value)

    def to(self, value):
        self.animation.stop()
        self.animation.setStartValue(self._value)
        self.animation.setEndValue(value)
        self.animation.start()

    def paint(self):
        if self._value < .01 or not self.owner.isEnabled():
            return
        painter = QPainter(self.owner)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for inset, alpha in ((1.5, 150), (3.5, 28), (5.5, 12)):
            painter.setPen(QPen(QColor(255, 200, 121, int(alpha * self._value)), 1.2))
            painter.drawRoundedRect(QRectF(self.owner.rect()).adjusted(inset, inset, -inset, -inset), 7, 7)


class MotionMixin:
    def enterEvent(self, event):
        super().enterEvent(event)
        self.halo.to(.7)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.halo.to(0.0)

    def setDown(self, down):
        super().setDown(down)
        if hasattr(self, 'halo'):
            if down:
                self.halo.animation.stop()
                self.halo.set_value(1.0)
            else:
                self.halo.to(0.0)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.halo.animation.stop()
        self.halo.set_value(1.0)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.halo.to(.7 if self.underMouse() else 0.0)

    def hideEvent(self, event):
        self.halo.animation.stop()
        self.halo.set_value(0.0)
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        self.halo.paint()


class MotionButton(MotionMixin, QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.halo = InteractionHalo(self)


class MotionToolButton(MotionMixin, QToolButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.halo = InteractionHalo(self)
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(50)
        self.activity_timer.timeout.connect(self.update)

    def _sync_activity(self):
        if self.property("active") and self.isVisible():
            self.activity_timer.start()
        else:
            self.activity_timer.stop()
        self.update()

    def event(self, event):
        if event.type() == QEvent.Type.DynamicPropertyChange and hasattr(self, "activity_timer"):
            if bytes(event.propertyName()) == b"active":
                self._sync_activity()
        return super().event(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_activity()

    def hideEvent(self, event):
        self.activity_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        nav, dock = self.property("nav"), self.property("dockAction")
        if not nav and not dock:
            return super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        selected = bool(self.property("selected"))
        active = bool(self.property("active"))
        pulse = .5 + .5 * math.sin(time.monotonic() * 2 * math.pi / 1.5) if active else 0
        accent = selected or active or self.property("role") == "primary"
        hover = max(self.halo.get_value(), 1.0 if self.isDown() else 0.0) if self.isEnabled() else 0
        if (nav and selected) or hover > .01 or self.isDown():
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0, QColor("#4d3b23") if selected else QColor(255, 187, 94, int(22*hover)))
            gradient.setColorAt(1, QColor("#181a19") if selected else QColor(255, 187, 94, 0))
            p.setBrush(gradient)
            p.setPen(QPen(QColor("#b8915d") if selected else QColor(255, 198, 116, int(100*hover)), 1))
            p.drawRoundedRect(area, 5, 5)
        if selected:
            p.setPen(QPen(QColor("#ffd084"), 2))
            p.drawLine(5, 1, self.width()-5, 1)
        size = (32 if self.height() >= 72 else 26) if nav else (38 if self.height() >= 78 else 30)
        icon_y = (12 if self.height() >= 72 else 5) if nav else (self.height()-size-22)/2-3
        icon_area = QRectF((self.width()-size)/2, icon_y, size, size)
        if accent or (dock and self.property("recordAction")):
            glow = QRadialGradient(icon_area.center(), size*.8)
            tint = QColor("#ff5b4e") if self.property("recordAction") else QColor("#ffc370")
            tint.setAlpha(int(36 + pulse * 40) if active else 45 if self.isEnabled() else 22)
            glow.setColorAt(0, tint)
            tint.setAlpha(0)
            glow.setColorAt(1, tint)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(icon_area.center(), size*.8, size*.8)
        p.setOpacity(1.0 if self.isEnabled() else .62)
        self.icon().paint(p, icon_area.toRect(), Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal,
                          QIcon.State.On if accent else QIcon.State.Off)
        if active:
            p.setPen(Qt.PenStyle.NoPen)
            if self.property("recordAction"):
                # Solid inner REC light, with a slow pulse that never disappears.
                tint = QColor("#ff514b")
                tint.setAlpha(int(150 + 105 * pulse))
                p.setBrush(tint)
                radius = size * (.13 + .025 * pulse)
                p.drawEllipse(icon_area.center(), radius, radius)
            else:
                tint = QColor("#65e5a3")
                tint.setAlpha(int(155 + 100 * pulse))
                p.setBrush(tint)
                p.drawEllipse(QRectF(icon_area.right() + 3, icon_area.top() + 1, 6, 6))
        p.setPen(QColor("#ffca80") if accent else QColor("#efeeea"))
        font = QFont("Avenir Next")
        font.setPixelSize(12 if nav else 11)
        font.setWeight(QFont.Weight.Medium if selected else QFont.Weight.Normal)
        if dock:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        p.setFont(font)
        caption = self.text() if nav else self.text().upper()
        text_area = QRectF(6, self.height()-25, self.width()-12, 21)
        p.drawText(text_area, Qt.AlignmentFlag.AlignCenter, p.fontMetrics().elidedText(caption, Qt.TextElideMode.ElideRight, int(text_area.width())))


def repolish(widget: QWidget) -> None:
    signature = (widget.styleSheet(), tuple((bytes(name), repr(widget.property(bytes(name).decode())))
                                            for name in widget.dynamicPropertyNames()))
    if getattr(widget, '_polish_signature', None) == signature:
        return
    widget._polish_signature = signature
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class StatusBadge(QLabel):
    def __init__(
        self,
        text: str,
        status: str = "offline",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(status)

    def set_status(self, status: str, text: str | None = None) -> None:
        if self.property("status") == status and (text is None or self.text() == text):
            return
        if text is not None:
            self.setText(text)
        self.setProperty("status", status)
        repolish(self)


class MetricChip(QFrame):
    def __init__(
        self,
        label: str,
        value: str = "—",
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setMinimumWidth(118)
        self.setProperty("metric", True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(10)
        symbol = {"Поток": "stream", "Приём": "transfer", "Экран": "video", "Кодек": "codec", "Разрешение": "image"}.get(label, "radio")
        self.symbol = QLabel()
        self.symbol.setPixmap(ui_icon(symbol).pixmap(24, 24))
        layout.addWidget(self.symbol)
        text = QVBoxLayout()
        text.setSpacing(0)

        caption = QLabel(label.upper())
        caption.setProperty("metricCaption", True)

        self.value_label = QLabel(value)
        self.value_label.setProperty("metricValue", True)

        values = QHBoxLayout()
        values.setSpacing(4)
        values.addWidget(self.value_label)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("muted", True)
            hint_label.setStyleSheet("font-size: 11px;")
            values.addWidget(hint_label, 0, Qt.AlignmentFlag.AlignBottom)
        values.addStretch()
        text.addLayout(values)
        text.addWidget(caption)
        layout.addLayout(text)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class InlineMetric(QWidget):
    def __init__(self, caption, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        title = QLabel(caption)
        title.setProperty("muted", True)
        row.addWidget(title)
        self.value = QLabel("—")
        self.value.setProperty("inlineValue", True)
        row.addWidget(self.value)
        row.addStretch()

    def set_value(self, value):
        self.value.setText(value)


class ModuleCard(QFrame):
    def __init__(
        self,
        title: str,
        description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(11)

        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)

        title_label = QLabel(title)
        title_label.setProperty("section", True)

        description_label = QLabel(description)
        description_label.setProperty("muted", True)

        title_box.addWidget(title_label)
        title_box.addWidget(description_label)

        self.state_label = StatusBadge("НЕ ПОДКЛЮЧЕН", "offline")

        top.addLayout(title_box)
        top.addStretch(1)
        top.addWidget(self.state_label)

        detail_row = QHBoxLayout()
        detail_row.setSpacing(10)

        self.id_label = QLabel("ID: —")
        self.id_label.setProperty("muted", True)
        self.id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.trust_label = QLabel("Доверие: не установлено")
        self.trust_label.setProperty("muted", True)

        detail_row.addWidget(self.id_label)
        detail_row.addWidget(self.trust_label)
        detail_row.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.service_button = QPushButton("Перезапустить службу")
        self.service_button.setProperty("role", "ghost")
        self.service_button.setToolTip("Станет доступно после доверенной привязки модуля.")

        self.reboot_button = QPushButton("Перезагрузить модуль")
        self.reboot_button.setProperty("role", "ghost")
        self.reboot_button.setToolTip("Станет доступно после доверенной привязки модуля.")

        self.shutdown_button = QPushButton("Выключить")
        self.shutdown_button.setProperty("role", "danger")
        self.shutdown_button.setToolTip("Станет доступно после доверенной привязки модуля.")

        for button in (self.service_button, self.reboot_button, self.shutdown_button):
            button.setEnabled(False)
            actions.addWidget(button)

        actions.addStretch(1)

        root.addLayout(top)
        root.addLayout(detail_row)
        root.addLayout(actions)

    def update_state(self, state: str, module_id: str | None) -> None:
        self.id_label.setText(f"ID: {module_id or '—'}")

        status_kind = self._status_kind(state)
        self.state_label.set_status(status_kind, state.upper())

        # Destructive controls remain disabled until authenticated pairing exists.
        for button in (self.service_button, self.reboot_button, self.shutdown_button):
            button.setEnabled(False)

    @staticmethod
    def _status_kind(state: str) -> str:
        if state in {"готов", "активен"}:
            return "ready"
        if state in {"предупреждение", "загрузка", "проверка", "переподключение"}:
            return "warning"
        if state in {"ошибка", "несовместим"}:
            return "error"
        return "offline"


class PageHeader(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str = "",
        eyebrow: str = "FIT-LAB STATION",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        eyebrow_label = QLabel(eyebrow)
        eyebrow_label.setProperty("eyebrow", True)
        layout.addWidget(eyebrow_label)

        title_label = QLabel(title)
        title_label.setProperty("title", True)
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("muted", True)
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)
