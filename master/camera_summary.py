"""Readable device information, with settings taken from the latest readback."""
from pathlib import PurePosixPath


def camera_summary(profile, settings=None):
    values = dict((profile or {}).get('values', {}))
    config = (settings if settings is not None else (profile or {}).get('settings', {})).get('config', {})
    video, osd = config.get('video0', {}), config.get('osd', {})
    for destination, source in (('codec', 'codec'), ('size', 'size'), ('fps', 'fps'),
                                ('bitrate', 'bitrate'), ('gop', 'gopSize')):
        if source in video:
            values[destination] = video[source]
    for destination, source in (('osd_enabled', 'enabled'), ('osd_template', 'template')):
        if source in osd:
            values[destination] = osd[source]
    result = {key: str(value) if value is not None and value != '' else '—' for key, value in values.items()}
    for key, suffix in (('fps', ' FPS'), ('bitrate', ' кбит/с'), ('gop', ' с')):
        if result.get(key, '—') != '—':
            result[key] += suffix
    result['codec'] = {'h264': 'H.264', 'h265': 'H.265'}.get(str(values.get('codec')), result.get('codec', '—'))
    result['size'] = result.get('size', '—').replace('x', ' × ')
    result['osd_enabled'] = {'true': 'Включено', 'false': 'Выключено'}.get(str(values.get('osd_enabled')).lower(), '—')
    for key in ('radio_service', 'radio_tunnel', 'adaptive_link'):
        result[key] = '—' if key not in values else 'Установлена' if values[key] else 'Не обнаружена'
    if values.get('radio_driver'):
        result['radio_driver'] = PurePosixPath(str(values['radio_driver'])).name
    from master.camera_capabilities import summary
    result.update(summary((profile or {}).get('assessment')))
    return result
