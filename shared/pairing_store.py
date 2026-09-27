"""Private WFB key pairs and public durable receipts on the data disk."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Ссылка вместо файла привязки')
    temp = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def public_fingerprint(data):
    return 'SHA256:' + hashlib.sha256(data).hexdigest()


class PairingStore:
    def __init__(self, data_root):
        self.root = Path(data_root)
        self.private = self.root.parent / 'private/bindings'
        self.config = self.root / 'config'
        self.active_key = self.root.parent / 'private/runcam/gs.key'
        self.pending_path = self.config / 'pending-pairing.json'
        self.active_path = self.config / 'radio-binding.json'

    def folder(self, ticket):
        if not re.fullmatch(r'[0-9a-f]{32}', ticket):
            raise ValueError('Неверный идентификатор привязки')
        return self.private / ticket

    def read(self, path):
        return json.loads(path.read_text()) if path.exists() else None

    def pending(self):
        return self.read(self.pending_path)

    def save(self, receipt):
        self.config.mkdir(parents=True, exist_ok=True)
        atomic_write(self.pending_path, json.dumps(receipt, ensure_ascii=False).encode())

    def create(self, identity, host, fingerprint, reuse=None):
        from nacl.public import PrivateKey
        if not re.fullmatch(r'[0-9a-f]{24}', identity):
            raise ValueError('Неверная идентичность камеры')
        if self.pending():
            raise ValueError('Сначала завершите предыдущую привязку')
        self.private.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.private.chmod(0o700)
        ticket = secrets.token_hex(16)
        folder = self.folder(ticket)
        folder.mkdir(mode=0o700)
        if reuse:
            previous = self.folder(reuse['ticket'])
            gs_data, drone_data = [(previous / name).read_bytes() for name in ('gs.key', 'drone.key')]
            if len(gs_data) != 64 or len(drone_data) != 64:
                raise ValueError('Повреждён сохранённый профиль привязки')
            gs, drone = PrivateKey(gs_data[:32]), PrivateKey(drone_data[:32])
            if gs_data[32:] != bytes(drone.public_key) or drone_data[32:] != bytes(gs.public_key):
                raise ValueError('Сохранённая пара ключей не согласована')
        else:
            gs, drone = PrivateKey.generate(), PrivateKey.generate()
        atomic_write(folder / 'gs.key', bytes(gs) + bytes(drone.public_key))
        atomic_write(folder / 'drone.key', bytes(drone) + bytes(gs.public_key))
        if self.active_key.is_symlink():
            raise ValueError('Ссылка вместо ключа приёмника')
        old = self.active_key.read_bytes() if self.active_key.is_file() else None
        if old is not None:
            if self.active_key.is_symlink() or len(old) != 64:
                raise ValueError('Неверный текущий ключ приёмника')
            atomic_write(folder / 'previous-gs.key', old)
        receipt = dict(schema=1, ticket=ticket, identity=identity, host=host,
                       ssh_fingerprint=fingerprint, stage='prepared', had_previous=old is not None,
                       gs_public=public_fingerprint(bytes(gs.public_key)),
                       drone_public=public_fingerprint(bytes(drone.public_key)))
        self.save(receipt)
        return receipt

    def activate(self, receipt):
        receipt['stage'] = 'activating'
        self.save(receipt)
        self.active_key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.active_key, (self.folder(receipt['ticket']) / 'gs.key').read_bytes())

    def finish(self, receipt, committed):
        folder = self.folder(receipt['ticket'])
        if committed:
            atomic_write(self.active_key, (folder / 'gs.key').read_bytes())
            receipt['stage'] = 'committed'
            encoded = json.dumps(receipt, ensure_ascii=False).encode()
            atomic_write(self.active_path, encoded)
            profiles = self.config / 'bindings'
            profiles.mkdir(exist_ok=True)
            atomic_write(profiles / (receipt['identity'] + '.json'), encoded)
            if receipt.get('receiver_config'):
                preferences_path = self.config / 'interface.json'
                preferences = self.read(preferences_path) or {}
                preferences.update(receipt['receiver_config'])
                atomic_write(preferences_path, json.dumps(preferences, ensure_ascii=False).encode())
        else:
            if receipt['had_previous']:
                atomic_write(self.active_key, (folder / 'previous-gs.key').read_bytes())
            elif self.active_key.exists():
                self.active_key.unlink()
            receipt['stage'] = 'rolled_back'
        atomic_write(folder / 'receipt.json', json.dumps(receipt, ensure_ascii=False).encode())
        self.pending_path.unlink(missing_ok=True)

    def guard(self):
        selection = self.config / 'pending-selection.json'
        if selection.exists():
            import fcntl
            with (self.config / '.pairing.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._activate_saved(self.read(selection))
        pending = self.pending()
        if pending and os.environ.get('FIT_LAB_PAIRING_ID') != pending['ticket']:
            raise ValueError('Незавершённая привязка · подключите камеру по LAN')
        if not pending:
            active = self.read(self.active_path)
            saved = self.read(self.config / 'bindings' / (active['identity'] + '.json')) if active else None
            if saved and saved.get('archived'):
                raise ValueError('Камера удалена из списка · выберите или свяжите другую камеру')

    def profiles(self, include_archived=False):
        result = []
        for path in sorted((self.config / 'bindings').glob('*.json')):
            try:
                item = self.read(path)
                if (item and item.get('stage') == 'committed' and
                        (include_archived or not item.get('archived')) and re.fullmatch(r'[0-9a-f]{24}', item['identity'])):
                    self.key_for(item)
                    result.append(item)
            except (OSError, ValueError, KeyError):
                continue
        return result

    def set_archived(self, identity, archived=True, *, revoke=False):
        """Reversible removal from discovery; never rotate or erase radio keys."""
        import fcntl
        if not re.fullmatch(r'[0-9a-f]{24}', identity):
            raise ValueError('Неизвестная камера')
        with (self.config / '.pairing.lock').open('a') as lock, (self.root / 'logs/.fit-lab-radio-prepare.lock').open('a') as radio_lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(radio_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.pending() or (self.config / 'pending-selection.json').exists():
                raise ValueError('Дождитесь завершения привязки камеры')
            path = self.config / 'bindings' / (identity + '.json')
            profile = self.read(path)
            if not profile or profile.get('stage') != 'committed':
                raise ValueError('Нет сохранённой камеры')
            if profile.get('revoked') and not archived:
                raise ValueError('Доверие отозвано. Если камера найдена, обновите ключи по LAN.')
            if not archived:
                self.key_for(profile)
            profile['archived'] = bool(archived)
            if revoke:
                if not archived:
                    raise ValueError('Отзыв требует исключения камеры из поиска')
                profile['revoked'] = True
            atomic_write(path, json.dumps(profile, ensure_ascii=False).encode())
            active = self.read(self.active_path)
            if archived and active and active.get('identity') == identity:
                others = self.profiles()
                if others:
                    atomic_write(self.config / 'pending-selection.json', json.dumps(others[0]).encode())
                    self._activate_saved(others[0])
            return profile

    def camera_identity(self, key_bytes, fingerprint, mac):
        """Preserve a uniquely pinned legacy profile during its first renewal."""
        identity = hashlib.sha256(key_bytes + b'\0' + mac.encode()).hexdigest()[:24]
        legacy = hashlib.sha256(key_bytes).hexdigest()[:24]
        profiles = self.profiles(include_archived=True)
        if any(p['identity'] == identity for p in profiles):
            return identity
        matches = [p for p in profiles if (p.get('legacy_import') or p.get('ethernet_mac') == mac) and
                   p['ssh_fingerprint'] == fingerprint and p['identity'] == legacy]
        return matches[0]['identity'] if len(matches) == 1 else identity

    def key_for(self, profile):
        path = self.folder(profile['ticket']) / 'gs.key'
        if path.is_symlink() or not path.is_file() or path.stat().st_size != 64:
            raise ValueError('Повреждён сохранённый ключ камеры')
        from nacl.public import PrivateKey
        key = path.read_bytes()
        if (profile.get('gs_public') != public_fingerprint(bytes(PrivateKey(key[:32]).public_key))
                or profile.get('drone_public') != public_fingerprint(key[32:])):
            raise ValueError('Сохранённый ключ не соответствует профилю камеры')
        return path

    def _activate_saved(self, known):
        if not known or not re.fullmatch(r'[0-9a-f]{24}', known['identity']):
            raise ValueError('Неизвестная камера')
        if known.get('archived'):
            raise ValueError('Камера удалена из списка')
        payload = self.key_for(known).read_bytes()
        from shared.radio_settings import receiver_settings
        tuning = known['receiver_config']
        receiver_settings(tuning['radio_channel'], tuning['radio_width'])
        atomic_write(self.active_key, payload)
        encoded = json.dumps(known, ensure_ascii=False).encode()
        atomic_write(self.active_path, encoded)
        atomic_write(self.config / 'bindings' / (known['identity'] + '.json'), encoded)
        preferences = self.read(self.config / 'interface.json') or {}
        preferences.update(tuning)
        atomic_write(self.config / 'interface.json', json.dumps(preferences, ensure_ascii=False).encode())
        (self.config / 'pending-selection.json').unlink(missing_ok=True)

    def select_known(self, identity, tuning=None):
        import fcntl
        if not re.fullmatch(r'[0-9a-f]{24}', identity):
            raise ValueError('Неизвестная камера')
        with (self.config / '.pairing.lock').open('a') as lock, (self.root / 'logs/.fit-lab-radio-prepare.lock').open('a') as radio_lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(radio_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            known = self.read(self.config / 'bindings' / (identity + '.json'))
            if not known or known['stage'] != 'committed':
                raise ValueError('Нет проверенной привязки этой камеры')
            if known.get('archived'):
                raise ValueError('Камера удалена из списка')
            if self.pending():
                raise ValueError('Сначала завершите привязку камеры')
            if tuning:
                known['receiver_config'].update(radio_channel=tuning['channel'], radio_width=tuning['width'])
            self.key_for(known)
            atomic_write(self.config / 'pending-selection.json', json.dumps(known).encode())
            self._activate_saved(known)
            return known

    def remember_tuning(self, fingerprint, **values):
        """Only authenticated readback for this active camera can amend its profile."""
        import fcntl
        if self.pending() or (self.config / 'pending-selection.json').exists():
            return
        with (self.config / '.pairing.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            active = self.read(self.active_path)
            if not active or active.get('ssh_fingerprint') != fingerprint:
                return
            active['receiver_config'].update({k: v for k, v in values.items()
                                              if k in ('radio_channel', 'radio_width', 'codec')})
            encoded = json.dumps(active, ensure_ascii=False).encode()
            atomic_write(self.active_path, encoded)
            atomic_write(self.config / 'bindings' / (active['identity'] + '.json'), encoded)
