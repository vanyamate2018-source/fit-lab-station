"""Offline, read-only guidance from already sampled station state."""
from datetime import datetime, timezone


def assess(state, running, screens, touch, writable):
    issues = []
    if not writable:
        issues.append({'code': 'storage', 'message': 'Папка записи недоступна', 'action': 'Выберите другой накопитель.'})
    if running and state.get('phase') not in ('video', 'decoding'):
        issues.append({'code': 'video', 'message': 'Ожидание изображения', 'action': 'Проверьте питание камеры и выбранный профиль.'})
    health = state.get('health') or {}
    if running and (health.get('loss_percent') or 0) > 1:
        issues.append({'code': 'loss', 'message': 'Есть потери радиопакетов', 'action': 'Проверьте антенны и питание; оцените помехи.'})
    if screens and any(s['width'] < 800 or s['height'] < 480 for s in screens):
        issues.append({'code': 'screen', 'message': 'Мало места на экране', 'action': 'Выберите компактный интерфейс или большее разрешение.'})
    # Whitelist only: never serialize camera credentials or arbitrary session data.
    return {'name': 'FIT-LAB Assistant', 'time': datetime.now(timezone.utc).isoformat(),
            'mode': 'read_only', 'screens': screens, 'touch': touch,
            'running': bool(running), 'phase': state.get('phase', 'idle'),
            'fps': state.get('fps'), 'mbps': state.get('mbps'),
            'audio': (state.get('audio') or {}).get('state', 'unknown'),
            'control': (state.get('control') or {}).get('state', 'unknown'),
            'receivers': [{'index': r.get('index'), 'connection': r.get('connection'),
                           'rssi_dbm': r.get('rssi_dbm')} for r in state.get('receivers', [])],
            'issues': issues}
