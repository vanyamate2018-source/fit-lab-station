"""Independent splash rendering while the GUI constructs its native widgets."""
import json
import os
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class StartupScreen(QObject):
    ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedErrorChannel)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.errorOccurred.connect(self._failed)
        self.process.finished.connect(self._failed)
        self.started = False
        self.fallback = None
        self.buffer = b''
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._failed)

    def show(self):
        self.process.start(sys.executable, ['-m', 'master.startup_screen'])
        self.timeout.start(4000)

    def _read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        if b'READY\n' in self.buffer and not self.started:
            self.started = True
            self.timeout.stop()
            self.ready.emit()

    def _failed(self, *_):
        if self.started:
            return
        self.started = True
        self.timeout.stop()
        self.process.kill()
        from master.ui.brand import StartupSplash
        self.fallback = StartupSplash()
        self.fallback.show()
        self.ready.emit()

    def _send(self, **value):
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.write((json.dumps(value) + '\n').encode())

    def stage(self, value, caption):
        if self.fallback:
            self.fallback.stage(value, caption)
        else:
            self._send(stage=value, caption=caption)

    def finish_animated(self, window):
        if self.fallback:
            self.fallback.finish_animated(window)
        else:
            # Main window has been mapped behind the opaque splash. Let its
            # first layout/paint settle before removing the cover.
            QTimer.singleShot(300, lambda: self._send(finish=True))

    def close(self):
        self.timeout.stop()
        if self.fallback:
            self.fallback.close()
        self._send(close=True)


def main():
    from PySide6.QtCore import Qt, QSocketNotifier, QElapsedTimer
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication
    from master.ui.brand import StartupSplash, ASSET
    app = QApplication(sys.argv)
    splash = StartupSplash()
    screen = app.primaryScreen()
    if screen:
        size = screen.geometry().size()
        canvas = QPixmap(size)
        canvas.fill(QColor('#111617'))
        source = QPixmap(str(ASSET.with_name('vector-splash.png')))
        if source.isNull():
            source = splash.pixmap()
        art = source.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(canvas)
        painter.drawPixmap((size.width()-art.width())//2, (size.height()-art.height())//2, art)
        painter.end()
        splash.setPixmap(canvas)
        splash.move(screen.geometry().topLeft())
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.setWindowFlag(Qt.WindowType.X11BypassWindowManagerHint, True)
    splash.show()
    elapsed = QElapsedTimer()
    elapsed.start()
    pending = bytearray()
    notifier = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read)
    def read(*_):
        chunk = os.read(sys.stdin.fileno(), 4096)
        if not chunk:
            app.quit()
            return
        pending.extend(chunk)
        while b'\n' in pending:
            line, _, rest = pending.partition(b'\n')
            pending[:] = rest
            value = json.loads(line)
            if value.get('close'):
                app.quit()
            elif value.get('finish'):
                splash.stage(100, 'Готово')
                QTimer.singleShot(max(280, 5000-elapsed.elapsed()), app.quit)
            elif 'stage' in value:
                splash.stage(value['stage'], value['caption'])
    notifier.activated.connect(read)
    # Announce readiness only after the first paint has had an event-loop turn.
    QTimer.singleShot(80, lambda: print('READY', flush=True))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
