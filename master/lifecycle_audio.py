"""Play owner-supplied startup/shutdown clips outside the UI rendering thread."""
import shutil
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class LifecycleAudio(QObject):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.active = False
        self.process.finished.connect(self._finish)
        self.process.errorOccurred.connect(self._finish)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.cancel)

    def start(self, name, volume=50):
        path = Path(__file__).parent / 'assets' / 'voice' / (name+'.wav')
        if name not in ('hello', 'bye', 'connected', 'lost', 'record', 'saved', 'restored', 'receiver_lost', 'record_stopped', 'storage_full', 'settings_error', 'storage_lost', 'warning', 'master_lost', 'master_restored') or not path.is_file():
            return False
        volume = max(0, min(100, volume)) / 100
        player = shutil.which('afplay' if sys.platform == 'darwin' else 'paplay')
        if not player:
            return False
        args = ['-v', str(volume), str(path)] if sys.platform == 'darwin' else ['--volume='+str(int(volume*65536)), str(path)]
        import wave
        try:
            with wave.open(str(path), 'rb') as source:
                duration = source.getnframes()/source.getframerate()
        except (OSError, wave.Error):
            return False
        self.active = True
        self.timeout.start(int(min(60, duration+5)*1000))
        self.process.start(player, args)
        return True

    def _finish(self, *_):
        if not self.active:
            return
        self.active = False
        self.timeout.stop()
        self.finished.emit()

    def cancel(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(500)
        self._finish()
