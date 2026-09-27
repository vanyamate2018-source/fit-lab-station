"""Keep the station fitted to its touch display across hotplug and mode changes."""
from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication


def compact_navigation(width, height, mode='auto'):
    # Preserve the video area on short panels even with a manual preference.
    if height < 650 or width < 900:
        return True
    if mode == 'compact':
        return True
    if mode == 'comfortable':
        return False
    return width < 1100 or height < 760


class DisplayLayout(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.observed = set()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.fit)
        app = QApplication.instance()
        app.screenAdded.connect(self.schedule)
        app.screenRemoved.connect(self.schedule)
        self.bind_screens()
        QTimer.singleShot(0, self.bind_window)

    def bind_window(self):
        handle = self.window.windowHandle()
        if handle is not None and handle is not getattr(self, 'bound_handle', None):
            self.bound_handle = handle
            handle.screenChanged.connect(self.schedule)

    def bind_screens(self):
        for screen in QApplication.screens():
            if screen not in self.observed:
                self.observed.add(screen)
                screen.availableGeometryChanged.connect(self.schedule)
                screen.geometryChanged.connect(self.schedule)
                screen.logicalDotsPerInchChanged.connect(self.schedule)

    def schedule(self, *_):
        self.bind_screens()
        self.timer.start()

    def fit(self):
        window = self.window
        self.bind_window()
        target = window.screen() or QApplication.primaryScreen()
        if target is None:
            return
        if hasattr(window, 'display_info'):
            size = target.geometry().size()
            window.display_info.setText(f'{size.width()} × {size.height()} · {target.refreshRate():.0f} Гц')
        if hasattr(window, '_apply_navigation_size'):
            window._apply_navigation_size()
        if window.isFullScreen():
            return
        area = target.availableGeometry()
        # Fit the screen the user chose, without moving the window to MPI7009.
        if area.contains(window.frameGeometry()):
            return
        frame_height = max(24, window.frameGeometry().height()-window.geometry().height())
        available = area.adjusted(0, frame_height, 0, 0)
        window.resize(min(window.width(),available.width()),min(window.height(),available.height()))
        x=max(available.left(),min(window.x(),available.right()-window.width()+1))
        y=max(available.top(),min(window.y(),available.bottom()-window.height()+1))
        window.move(x,y)
