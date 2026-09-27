"""Camera logins in the OS vault, never in plaintext application settings."""
import ctypes
import hashlib
import json
import sys
from threading import RLock


class CameraCredentialStore:
    def __init__(self, root, backend=None):
        self.root, self.backend = root, backend
        self.cache = {}
        self.lock = RLock()

    @property
    def storage_name(self):
        return {'darwin': 'macos-keychain', 'win32': 'windows-credential-manager'}.get(sys.platform, 'linux-secret-service')

    def _native(self):
        if self.backend is None:
            if sys.platform != 'darwin':
                from master.credential_backends import SystemVault
                self.backend = SystemVault.for_platform(sys.platform)
                return self.backend
            self.backend = ctypes.CDLL(str(self.root / 'cache/native/camera-credentials.dylib'))
            self.backend.fitlab_credential_read.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t]
            self.backend.fitlab_credential_read.restype = ctypes.c_long
            self.backend.fitlab_credential_write.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t]
            self.backend.fitlab_credential_write.restype = ctypes.c_int
        return self.backend

    def _read(self, account):
        if account in self.cache:
            return self.cache[account]
        buffer = ctypes.create_string_buffer(8192)
        try:
            length = self._native().fitlab_credential_read(account.encode(), buffer, len(buffer))
            if length < 0:
                raise OSError('Keychain read failed: ' + str(length))
            if length == 0:
                return None
            raw = json.loads(buffer.raw[:length])
            if not isinstance(raw, list) or len(raw) != 2 or not all(isinstance(x, str) for x in raw):
                raise OSError('Invalid saved login')
            self.cache[account] = tuple(raw)
            return self.cache[account]
        finally:
            ctypes.memset(buffer, 0, len(buffer))

    def load(self, identity=None):
        with self.lock:
            return (self._read('camera:' + identity) if identity else None) or self._read('common')

    def durable_write(self, account, credentials):
        """Security changes require a real vault write and an uncached readback."""
        with self.lock:
            self._write(account, tuple(credentials))
            self.cache.pop(account, None)
            if self._read(account) != tuple(credentials):
                raise OSError('Secure storage did not confirm the write')

    def candidates(self, identity=None):
        """A pending password transaction can be recovered after a crash."""
        values = [self.load(identity)]
        if identity:
            path = security_receipt_path(self.root, identity)
            try:
                pending = json.loads(path.read_text()).get('stage') == 'pending'
            except (OSError, ValueError):
                pending = False
            if pending:
                with self.lock:
                    values += [self._read(prefix + identity) for prefix in ('rotation-new:', 'rotation-old:')]
        return list(dict.fromkeys(v for v in values if v))

    def remember(self, identity, credentials):
        credentials = tuple(credentials)
        if not identity or len(credentials) != 2 or not all(isinstance(x, str) and len(x) <= 2048 for x in credentials):
            raise ValueError('Invalid camera login')
        with self.lock:
            self.durable_write('camera:' + identity, credentials)
            # A different camera password must not replace the common fallback.
            if not self._read('common'):
                self._write('common', credentials)

    def _write(self, account, credentials):
        self.cache[account] = credentials
        encoded = json.dumps(credentials, ensure_ascii=False).encode()
        if len(encoded) > 8192:
            raise ValueError('Saved login too large')
        buffer = ctypes.create_string_buffer(encoded)
        try:
            status = self._native().fitlab_credential_write(account.encode(), buffer, len(encoded))
            if status:
                raise OSError('Keychain write failed: ' + str(status))
        finally:
            ctypes.memset(buffer, 0, len(buffer))


def security_receipt_path(root, identity):
    from pathlib import Path
    return Path(root) / 'config/camera-security' / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
