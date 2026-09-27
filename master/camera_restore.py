"""Per-camera, public settings snapshots; no passwords, keys or network config."""
import hashlib
import json
import os
import time
from pathlib import Path

from shared.camera_settings import fields, get_value, make_patch


class CameraRestoreStore:
    def __init__(self, root, fingerprint):
        if not fingerprint or not fingerprint.startswith('SHA256:'):
            raise ValueError('Сначала подтвердите подключение камеры')
        identity = hashlib.sha256(fingerprint.encode()).hexdigest()
        self.path = Path(root) / 'config' / 'camera-restore' / (identity + '.json')
        self.fingerprint = fingerprint

    def read(self):
        try:
            data = json.loads(self.path.read_text())
            if data.get('fingerprint') == self.fingerprint:
                return data
        except (OSError, ValueError):
            pass
        return {'fingerprint': self.fingerprint}

    def write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
        temporary.replace(self.path)

    def initial(self, settings):
        data = self.read()
        if 'initial' in data:
            return
        values = {path: spec['value'] for path, spec in fields(
            settings.get('schema', {}), settings.get('config', {})).items()
            if not spec.get('readOnly')}
        if values:
            data['initial'] = {'time': time.time(), 'values': values}
            self.write(data)

    def confirmed(self, schema, before, after, changes):
        if any(get_value(after, path) != value for path, value in changes.items()):
            raise ValueError('Откат не сохранён: применение параметров не подтверждено')
        available = fields(schema, before)
        # Only the leaves this confirmed operation changed can be undone.
        values = {path: available[path]['value'] for path in changes if path in available}
        if not values:
            return
        data = self.read()
        data['previous'] = {'time': time.time(), 'values': values,
                            'applied': dict(changes)}
        self.write(data)

    def patch(self, kind, settings):
        record = self.read().get(kind, {})
        values = record.get('values', {})
        if not values:
            raise ValueError('Для этой камеры ещё нет сохранённых параметров')
        schema, config = settings.get('schema', {}), settings.get('config', {})
        available = fields(schema, config)
        # Do not silently undo a later edit made outside FIT-LAB.
        if kind == 'previous' and any(path not in available or
                available[path]['value'] != value for path, value in record.get('applied', {}).items()):
            raise ValueError('После сохранения параметры менялись. Обновите их и выберите исходные настройки.')
        values = {path: value for path, value in values.items() if path in available and not available[path].get('readOnly')}
        return make_patch(schema, config, values)


def default_patch(schema, config, group):
    values = {path: spec['default'] for path, spec in fields(schema, config).items()
              if path.split('.')[0] == group and 'default' in spec and not spec.get('readOnly')}
    return make_patch(schema, config, values)
