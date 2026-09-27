"""Asynchronous spectator AP lifetime tied to the stream, not the window."""
import json
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, Signal


class Hotspot(QObject):
    ready = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.started.connect(lambda: self.process.write(b'start\n'))
        self.process.errorOccurred.connect(lambda _: self.error.emit('Не удалось запустить управление Wi-Fi'))
        self.buffer = b''
        self.wanted = False

    def start(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            raise ValueError('Wi-Fi ещё завершает предыдущую трансляцию')
        self.wanted = True
        self.buffer = b''
        self.process.start(sys.executable, ['-u', '-m', 'master.hotspot_worker'])

    def read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        lines = self.buffer.split(b'\n'); self.buffer = lines.pop()[-4096:]
        for line in lines:
            try: event = json.loads(line)
            except ValueError: continue
            if event.get('state') == 'ready' and self.wanted:
                self.ready.emit(event['address'])
            elif event.get('state') == 'error':
                self.error.emit(event.get('error', 'Ошибка Wi-Fi'))

    def stop(self):
        self.wanted = False
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.write(b'stop\n')
            self.process.closeWriteChannel()

    def close(self):
        self.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.waitForFinished(18000)
