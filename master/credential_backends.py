"""Explicit secure providers; never select third-party plaintext fallbacks."""
import ctypes


class SystemVault:
    service = 'FIT-LAB Camera Access'

    def __init__(self, provider):
        self.provider = provider

    @classmethod
    def for_platform(cls, platform):
        try:
            if platform == 'win32':
                from keyring.backends.Windows import WinVaultKeyring
                provider = WinVaultKeyring()
            elif platform.startswith('linux'):
                from keyring.backends.SecretService import Keyring
                provider = Keyring()
            else:
                raise OSError('Unsupported secure storage platform')
            # A headless Linux host may have no unlocked Secret Service.
            # Password rotation must fail before changing camera credentials.
            if provider.priority <= 0:
                raise OSError('System vault unavailable')
            return cls(provider)
        except Exception:
            raise OSError('Защищённое хранилище ОС недоступно. Постоянное сохранение не выполнено.') from None

    def fitlab_credential_read(self, account, buffer, length):
        try:
            value = self.provider.get_password(self.service, account.decode())
            if value is None:
                return 0
            encoded = value.encode()
            if len(encoded) > length:
                return -1
            ctypes.memmove(buffer, encoded, len(encoded))
            return len(encoded)
        except Exception:
            return -1

    def fitlab_credential_write(self, account, data, length):
        try:
            value = ctypes.string_at(data, length).decode()
            self.provider.set_password(self.service, account.decode(), value)
            return 0
        except Exception:
            return -1
