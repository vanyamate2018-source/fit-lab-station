"""Background, bounded synchronization to the configured, SSH-pinned receiver."""
import hashlib
import queue
import threading
import time
from shared.binding_transfer import export_bindings
from master.binding_sync import sync_bindings


class ModuleInitialization:
    def __init__(self, root, host, credentials):
        self.root, self.host, self.credentials = root, host, credentials
        self.messages = queue.Queue()
        self.busy = False
        self.next_try = 0
        self.last_digest = None
        self.last_success = 0
        self.last_error = None

    def tick(self):
        now = time.monotonic()
        if self.busy or now < self.next_try:
            return
        self.busy = True
        self.next_try = now + 20
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            payload = export_bindings(self.root/'data', self.credentials)
            digest = hashlib.sha256(payload).digest()
            if digest == self.last_digest and time.monotonic() - self.last_success < 60:
                return
            sync_bindings(self.root, self.host, self.credentials)
            if digest != self.last_digest or self.last_error:
                self.messages.put('Приёмник готов · сохранённые камеры синхронизированы')
            self.last_digest = digest
            self.last_success = time.monotonic()
            self.last_error = None
        except Exception:
            message = 'Синхронизация приёмника ожидает защищённого подключения и доступа к хранилищу'
            if self.last_error != message:
                self.messages.put(message)
            self.last_error = message
        finally:
            self.busy = False
