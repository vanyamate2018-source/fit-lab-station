"""App-local digitizer support; never posts input into other applications."""
from __future__ import annotations

import json
import os
import sys
import time
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, QPointF, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QRadialGradient, QInputDevice
from PySide6.QtWidgets import QApplication, QAbstractButton, QAbstractScrollArea, QWidget, QComboBox, QLineEdit, QSpinBox
from shiboken6 import isValid

from shared.touch import decode_qdtech


def show_touch_ring(window, point):
    # Touch input stays active; visual tap markers are disabled by default.
    if not getattr(window, 'preferences', {}).get('touch_ripple', False):
        return
    now = time.monotonic()
    previous = getattr(window, '_last_touch_ring', None)
    if previous and now - previous[0] < .1 and (point - previous[1]).manhattanLength() < 16:
        return
    window._last_touch_ring = (now, point)
    rings = window.findChildren(TouchRing, options=Qt.FindChildOption.FindDirectChildrenOnly)
    if len(rings) >= 4:
        return
    TouchRing(window, point)


class TouchRing(QWidget):
    def __init__(self, window, point):
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")
        self.resize(72, 72)
        self.born = time.monotonic()
        self.move(point.x()-36, point.y()-36)
        self.show()
        self.raise_()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(20)

    def advance(self):
        if time.monotonic() - self.born > .38:
            self.timer.stop()
            self.deleteLater()
        else:
            self.update()

    def paintEvent(self, _):
        progress = min(1, (time.monotonic()-self.born)/.38)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        eased = 1 - (1-progress)**3
        radius = 13 + 20*eased
        alpha = 1-progress
        glow = QRadialGradient(QPointF(36, 36), radius)
        glow.setColorAt(0, QColor(255, 216, 160, int(82*alpha)))
        glow.setColorAt(.65, QColor(255, 196, 110, int(45*alpha)))
        glow.setColorAt(1, QColor(255, 196, 110, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(36, 36), radius, radius)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 215, 160, int(110*alpha)), 1))
        p.drawEllipse(QPointF(36, 36), radius*.78, radius*.78)


class TouchSupport(QObject):
    statusChanged = Signal(str)

    def __init__(self, window, data_root, start_reader=True, status_file="touch-status.json"):
        super().__init__(window)
        self.window = window
        self.auto_cursor = sys.platform == 'linux' and os.environ.get('FIT_LAB_EMBEDDED_RECEIVER') == '1'
        self.cursor_hidden = False
        self.data_root = Path(data_root)
        self.status_file = status_file
        self.contacts = {}
        self.ignored = set()
        self.last_report = 0.0
        self.max_contacts = self.reports = self.taps = 0
        self.last_saved = 0.0
        self.system_mode = False
        self.linux_devices = []
        self.last_linux_scan = -10.0
        self.sending = False
        self.buffer = bytearray()
        self.connected = False
        self.status = "Сенсор не подключён"
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(lambda _: self.set_status("Сенсор: модуль недоступен"))
        self.watchdog = QTimer(self)
        self.watchdog.timeout.connect(self.check_stale)
        self.watchdog.start(500)
        # An application-wide Python filter wraps QtQuick internal objects during
        # construction and crashes PySide6/QtWebEngine. Filter owned widgets only.
        self.filtered = []
        self.attach(window)
        if start_reader and sys.platform == "darwin":
            executable = self.data_root / "cache/native/fitlab-touch-reader"
            if executable.is_file():
                self.process.start(str(executable), [])
            else:
                self.set_status("Сенсор: модуль не собран")

    def attach(self, window):
        from PySide6.QtWidgets import QScrollArea, QAbstractItemView
        from master.ui.scrolling import configure_touch_scrolling
        for widget in [window, *window.findChildren(QWidget)]:
            if isinstance(widget, (QScrollArea, QAbstractItemView)):
                configure_touch_scrolling(widget)
            if self.auto_cursor or isinstance(widget, (QAbstractButton, QComboBox, QLineEdit, QSpinBox)):
                if self.auto_cursor:
                    widget.setMouseTracking(True)
                widget.installEventFilter(self)
                self.filtered.append(weakref.ref(widget))

    def set_status(self, text):
        self.status = text
        self.statusChanged.emit(text)

    def observe_cursor(self, event):
        if not self.auto_cursor:
            return
        kind = event.type()
        touch = kind in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd)
        mouse = kind in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress)
        if mouse:
            device = event.pointingDevice()
            touch = (device is not None and device.type() == QInputDevice.DeviceType.TouchScreen) or event.source() != Qt.MouseEventSource.MouseEventNotSynthesized
        if touch and not self.cursor_hidden:
            QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
            self.cursor_hidden = True
        elif mouse and not touch and self.cursor_hidden:
            QApplication.restoreOverrideCursor()
            self.cursor_hidden = False

    def eventFilter(self, obj, event):
        if not isinstance(obj, QWidget):
            return False
        self.observe_cursor(event)
        kind = event.type()
        if kind == QEvent.Type.TouchBegin:
            for point in event.points()[:4]:
                show_touch_ring(obj.window(), obj.window().mapFromGlobal(point.globalPosition().toPoint()))
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            # A native mouse compatibility event must not execute a touch twice.
            if not self.sending and not self.system_mode and time.monotonic()-self.last_report < .12 and self.connected:
                return True
            if kind == QEvent.Type.MouseButtonPress and not self.sending:
                show_touch_ring(obj.window(), obj.window().mapFromGlobal(event.globalPosition().toPoint()))
        return False

    def read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b"\n" in self.buffer:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            try:
                event = json.loads(line)
                kind = event.get("type")
                if kind == "report":
                    points = decode_qdtech(bytes.fromhex(event["data"]))
                    self.reports += 1
                    self.max_contacts = max(self.max_contacts, len(points))
                    self.last_report = time.monotonic()
                    self.dispatch(points)
                elif kind == "connected":
                    self.connected = True
                    self.set_status("MPI7009 · сенсор подключён")
                elif kind == "removed":
                    self.cancel()
                    self.connected = False
                    self.set_status("Сенсор отключён · ожидание USB")
                elif kind == "open" and event.get("result"):
                    self.set_status("macOS: нет доступа к сенсору")
            except (ValueError, KeyError, TypeError):
                self.cancel()
        if len(self.buffer) > 16384:
            self.buffer.clear()
            self.cancel()

    def target_screen(self):
        return next((s for s in QApplication.screens() if "MPI7009" in s.name()), None)

    def dispatch(self, points):
        if self.system_mode:
            self.cancel()
            return
        screen = self.target_screen()
        if screen is None or QApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
            self.cancel()
            return
        geometry = screen.geometry()
        present = {point.id for point in points}
        self.ignored.intersection_update(present)
        for ident in list(self.contacts):
            if ident not in present:
                self.release(ident)
        for point in points:
            global_pos = geometry.topLeft() + QPointF(point.x*(geometry.width()-1), point.y*(geometry.height()-1)).toPoint()
            if point.id not in self.contacts and point.id not in self.ignored:
                self.press(point.id, global_pos)
                if point.id not in self.contacts:
                    self.ignored.add(point.id)
            elif point.id in self.contacts:
                self.move(point.id, global_pos)
        self.set_status(f"MPI7009 · касаний: {len(points)}" if points else "MPI7009 · сенсор готов")

    def press(self, ident, pos):
        target = QApplication.widgetAt(pos)
        modal = QApplication.activeModalWidget()
        if target is None or not target.isEnabled() or (modal and target.window() != modal):
            return
        # widgetAt only returns widgets owned by this process.
        ancestor = target
        scroll = None
        while ancestor:
            if isinstance(ancestor, QAbstractButton):
                target = ancestor
                break
            ancestor = ancestor.parentWidget()
        ancestor = target
        while ancestor:
            if isinstance(ancestor, QAbstractScrollArea):
                scroll = ancestor
                break
            ancestor = ancestor.parentWidget()
        if any(state["widget"]() == target for state in self.contacts.values()):
            return
        state = dict(widget=weakref.ref(target), start=pos, last=pos, moved=False,
                     scroll=weakref.ref(scroll) if scroll else None,
                     button=isinstance(target, QAbstractButton), mouse=False)
        self.contacts[ident] = state
        show_touch_ring(target.window(), target.window().mapFromGlobal(pos))
        if state["button"]:
            target.setDown(True)
        elif not any(s["mouse"] for s in self.contacts.values()):
            state["mouse"] = True
            self.mouse(target, QEvent.Type.MouseButtonPress, pos)

    def mouse(self, target, kind, pos):
        self.sending = True
        try:
            event = QMouseEvent(kind, QPointF(target.mapFromGlobal(pos)), QPointF(pos),
                Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(target, event)
        finally:
            self.sending = False

    def move(self, ident, pos):
        state = self.contacts[ident]
        target = state["widget"]()
        if target is None or not isValid(target):
            self.contacts.pop(ident, None)
            return
        delta = pos - state["last"]
        state["moved"] |= (pos-state["start"]).manhattanLength() > 18
        scroll = state["scroll"]() if state["scroll"] else None
        if state["moved"] and scroll and isValid(scroll):
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().value()-delta.y())
            if state["button"]:
                target.setDown(False)
        elif state["button"]:
            target.setDown(target.rect().contains(target.mapFromGlobal(pos)) and not state["moved"])
        elif state["mouse"]:
            self.mouse(target, QEvent.Type.MouseMove, pos)
        state["last"] = pos

    def release(self, ident, cancel=False):
        state = self.contacts.pop(ident)
        target = state["widget"]()
        if target is None or not isValid(target):
            return
        if state["button"]:
            modal = QApplication.activeModalWidget()
            activated = (not cancel and not state["moved"] and target.isDown() and target.isVisible()
                         and target.isEnabled() and (modal is None or target.window() == modal))
            target.setDown(False)
            if activated:
                self.taps += 1
                # A button can open a modal dialog: run it after report dispatch.
                def activate():
                    if isValid(target) and target.isVisible() and target.isEnabled():
                        target.click()
                QTimer.singleShot(0, activate)
        elif state["mouse"]:
            self.mouse(target, QEvent.Type.MouseButtonRelease,
                       target.mapToGlobal(target.rect().topLeft())-QPointF(100,100).toPoint() if cancel or state["moved"] else state["last"])

    def cancel(self):
        self.ignored.update(self.contacts)
        for ident in list(self.contacts):
            self.release(ident, cancel=True)

    def check_stale(self):
        now = time.monotonic()
        if sys.platform == "linux":
            if now-self.last_linux_scan >= 2:
                from shared.linux_touch import discover
                self.linux_devices = discover()
                self.last_linux_scan = now
                self.connected = bool(self.linux_devices)
                self.system_mode = self.connected
                text = " · ".join(d["name"] for d in self.linux_devices) + " · сенсор подключён" if self.connected else "Сенсор не подключён"
                if text != self.status:
                    self.set_status(text)
        try:
            system = json.loads((self.data_root / "logs/system-touch-status.json").read_text())
            self.system_mode = bool(system.get("enabled") and time.time()-system.get("timestamp", 0) < 2)
        except (OSError, ValueError):
            if sys.platform != "linux":
                self.system_mode = False
        if self.system_mode and sys.platform == "darwin":
            self.cancel()
            self.set_status("MPI7009 · управление macOS")
        if self.contacts and now-self.last_report > 2:
            self.cancel()
        if now-self.last_saved > 1:
            self.last_saved = now
            report = dict(connected=self.connected, reports=self.reports, max_contacts=self.max_contacts,
                          button_taps=self.taps, active_contacts=len(self.contacts), status=self.status,
                          native_devices=self.linux_devices)
            path = self.data_root / "logs" / self.status_file
            temporary = path.with_suffix(".tmp")
            try:
                temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                temporary.replace(path)
            except OSError:
                pass

    def finished(self, *_):
        self.cancel()
        self.connected = False
        self.set_status("Сенсор: модуль остановлен")

    def close(self):
        if self.cursor_hidden:
            QApplication.restoreOverrideCursor()
            self.cursor_hidden = False
        self.watchdog.stop()
        self.cancel()
        for reference in self.filtered:
            widget = reference()
            if widget is not None and isValid(widget):
                widget.removeEventFilter(self)
        self.process.terminate()
        if not self.process.waitForFinished(1200):
            self.process.kill()
            self.process.waitForFinished(500)
