"""Nonblocking discovery and mounting of removable data filesystems."""
import json
import sys
import time
from PySide6.QtCore import QObject, QProcess, QTimer


def mount_candidates(devices):
    result = []
    def protected(node):
        mounts = node.get('mountpoints') or []
        return any(m in ('/', '/boot', '/boot/efi', '/home') for m in mounts) or any(protected(c) for c in node.get('children', []))
    def walk(node, external=False):
        external = external or node.get('tran') == 'usb' or node.get('rm') in (True, 1, '1')
        path = node.get('path', '')
        fs = node.get('fstype')
        if (external and node.get('type') in ('disk', 'part') and fs
                and fs not in ('swap', 'crypto_LUKS', 'BitLocker', 'LVM2_member', 'linux_raid_member')
                and not any(node.get('mountpoints') or [])
                and path.startswith('/dev/') and '/' not in path[5:]):
            result.append(path)
        for child in node.get('children', []):
            walk(child, external)
    for device in devices:
        if not protected(device):
            walk(device)
    return result


class StorageMonitor(QObject):
    """Use the desktop's UDisks authorization; never sudo, format or repair."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.retry = {}
        self.queue = []
        self.mode = 'scan'
        self.target = None
        self.process = QProcess(self)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.failed)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.process.kill)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.scan)
        if sys.platform == 'linux':
            self.timer.start()
            QTimer.singleShot(500, self.scan)

    def scan(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.mode = 'scan'
        self.process.start('lsblk', ['--json', '--output', 'PATH,TYPE,FSTYPE,MOUNTPOINTS,TRAN,RM'])
        self.deadline.start(5000)

    def failed(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.deadline.stop()

    def finished(self, code, status):
        self.deadline.stop()
        output = bytes(self.process.readAllStandardOutput())
        self.process.readAllStandardError()
        if self.mode == 'scan':
            try:
                candidates = mount_candidates(json.loads(output).get('blockdevices', [])) if code == 0 else []
            except (ValueError, TypeError):
                candidates = []
            now = time.monotonic()
            self.retry = {p:t for p,t in self.retry.items() if p in candidates}
            self.queue = [p for p in candidates if now >= self.retry.get(p, 0)]
        self.mount_next()

    def mount_next(self):
        if not self.queue:
            return
        self.target = self.queue.pop(0)
        self.retry[self.target] = time.monotonic() + 30
        self.mode = 'mount'
        self.process.start('udisksctl', ['mount', '--no-user-interaction', '--block-device', self.target])
        self.deadline.start(8000)

    def stop(self):
        self.timer.stop()
        self.deadline.stop()
        self.queue.clear()
        self.process.kill()
