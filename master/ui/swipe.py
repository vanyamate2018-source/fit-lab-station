"""Single-finger navigation restricted to the bottom section bar."""
import time
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QAbstractButton


def swipe_direction(dx, dy):
    if abs(dx) < 60 or abs(dx) < abs(dy) * 1.5:
        return 0
    return 1 if dx < 0 else -1


class SectionSwipe(QObject):
    def __init__(self, bar, buttons, navigate):
        super().__init__(bar)
        self.navigate = navigate
        self.origin = None
        self.button = None
        self.cancelled = False
        self.dragged = False
        self.mouse_origin = None
        self.last_touch = -1.0
        for target in [bar, *buttons]:
            target.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
            target.installEventFilter(self)
        bar.setToolTip('Свайп влево или вправо — следующий раздел')

    def eventFilter(self, target, event):
        support = getattr(target.window(), 'touch', None)
        if support is not None and hasattr(support, 'observe_cursor'):
            support.observe_cursor(event)
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
            if self.origin is not None or time.monotonic() - self.last_touch < .35:
                event.accept()
                return True
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if not target.isEnabled():
                    return False
                self.mouse_origin = event.globalPosition()
                self.button = target if isinstance(target, QAbstractButton) else None
                self.dragged = False
                if self.button is not None:
                    self.button.setDown(True)
                event.accept()
                return True
            if self.mouse_origin is not None:
                delta = event.globalPosition() - self.mouse_origin
                self.dragged |= abs(delta.x()) >= 12 or abs(delta.y()) >= 12
                if self.dragged and self.button is not None:
                    self.button.setDown(False)
                if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                    button = self.button
                    self.mouse_origin = self.button = None
                    if button is not None:
                        button.setDown(False)
                    direction = swipe_direction(delta.x(), delta.y())
                    if direction:
                        self.navigate(direction)
                    elif not self.dragged and button is not None and button.isEnabled():
                        button.click()
                event.accept()
                return True
        if kind == QEvent.Type.TouchBegin:
            self.last_touch = time.monotonic()
            self.mouse_origin = None
            if len(event.points()) != 1:
                return False
            self.origin = event.points()[0].globalPosition()
            from master.ui.touch import show_touch_ring
            show_touch_ring(target.window(), target.window().mapFromGlobal(self.origin.toPoint()))
            self.button = target if isinstance(target, QAbstractButton) else None
            self.cancelled = False
            self.dragged = False
            if self.button is not None:
                self.button.setDown(True)
            event.accept()
            return True
        if self.origin is not None and kind in (QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            self.last_touch = time.monotonic()
            if kind == QEvent.Type.TouchCancel or len(event.points()) != 1:
                self.cancelled = True
            if len(event.points()) == 1:
                delta = event.points()[0].globalPosition() - self.origin
                if abs(delta.x()) >= 12 or abs(delta.y()) >= 12:
                    self.dragged = True
                    if self.button is not None:
                        self.button.setDown(False)
            if kind in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
                button = self.button
                if button is not None:
                    button.setDown(False)
                if not self.cancelled:
                    delta = event.points()[0].globalPosition() - self.origin
                    direction = swipe_direction(delta.x(), delta.y())
                    if direction:
                        self.navigate(direction)
                    elif not self.dragged and button is not None and button.isEnabled():
                        button.click()
                self.origin = self.button = None
            event.accept()
            return True
        return False
