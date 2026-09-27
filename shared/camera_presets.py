"""Convenience choices, filtered by firmware schema; never applied on load."""
from shared.camera_settings import fields, validate


def resolution_choices(spec):
    current = spec.get('value')
    values = spec.get('enum') or ['1280x720', '1920x1080']
    values = list(values)
    if current and current not in values:
        values.insert(0, current)
    return [(str(value).replace('x', ' × '), value) for value in values]


def video_presets(schema, config):
    available = fields(schema, config)
    result = []
    for size, label in [('1280x720', '720p'), ('1920x1080', '1080p')]:
        for fps in (30, 60):
            values = {'video0.size': size, 'video0.fps': fps}
            # Preserve codec, bitrate and image tuning: a video mode selector
            # must not silently change unrelated settings.
            try:
                for key, value in values.items():
                    spec = available[key]
                    if spec.get('readOnly'):
                        raise ValueError('read only')
                    validate(spec, value)
            except (KeyError, ValueError):
                continue
            result.append((f'{label} · {fps} FPS', values))
    return result


def link_video_profiles(schema, config):
    """Video-only profiles; advertised ranges are not a hardware benchmark."""
    available = fields(schema, config)
    keys = ('size', 'fps', 'codec', 'bitrate', 'rcMode', 'gopSize')
    current = {f'video0.{key}': config.get('video0', {}).get(key) for key in keys
               if f'video0.{key}' in available}
    result = [('Текущий · с камеры', current)] if current else []
    for label, fps, bitrate in [('Устойчивость · 720p / 30 · 3 Мбит/с', 30, 3072),
                                ('Плавность · 720p / 60 · 4 Мбит/с · тест', 60, 4096)]:
        values = dict(zip((f'video0.{key}' for key in keys),
                          ('1280x720', fps, 'h265', bitrate, 'cbr', '0.5')))
        try:
            for path, value in values.items():
                spec = available[path]
                if spec.get('readOnly'):
                    raise ValueError('read only')
                if path.endswith('gopSize') and spec['type'] != 'string':
                    values[path] = value = .5
                validate(spec, value)
        except (KeyError, ValueError):
            continue
        result.append((label, values))
    return result
