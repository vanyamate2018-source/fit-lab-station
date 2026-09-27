"""Read-only USB presence monitoring; does not open or initialize the radios."""
import plistlib
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class UsbMonitor(QObject):
    changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.closed = False
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.collect_timer = QTimer(self)
        self.collect_timer.setInterval(100)
        self.collect_timer.timeout.connect(self._collect)
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan)
        self.timer.start(2000)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.process.kill)
        self.last = None
        QTimer.singleShot(0, self.scan)

    def scan(self):
        if self.closed or self.pending is not None or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        from shared.usb_inventory import fast_devices
        self.pending = self.pool.submit(fast_devices)
        self.collect_timer.start()

    def _collect(self):
        if self.pending is None or not self.pending.done():
            return
        pending, self.pending = self.pending, None
        self.collect_timer.stop()
        try:
            devices = pending.result()
        except OSError:
            return  # An enumeration failure is not a disconnect.
        if devices is not None:
            self._publish(devices)
            return
        self.process.start("/usr/sbin/ioreg", ["-p", "IOUSB", "-a", "-l"])
        self.timeout.start(3000)

    def _finished(self, code, _):
        self.timeout.stop()
        if code:
            return
        try:
            raw = plistlib.loads(bytes(self.process.readAllStandardOutput()))
        except Exception:
            return
        devices = []
        def walk(value):
            if isinstance(value, dict):
                if (value.get("idVendor"), value.get("idProduct")) == (0x0bda, 0x8812) and "bNumConfigurations" in value:
                    devices.append({"address": value.get("USB Address", value.get("kUSBAddress")),
                                    "location": value.get("locationID", 0)})
                for item in value.values():
                    if isinstance(item, (dict, list)):
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(raw)
        devices.sort(key=lambda item: item["location"])
        self._publish(devices)

    def _publish(self, devices):
        if devices != self.last:
            self.last = devices
            self.changed.emit(devices)

    def close(self):
        self.closed = True
        self.timer.stop()
        self.collect_timer.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.timeout.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
