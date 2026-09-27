"""Capability-driven Majestic settings. No guessed hardware ranges or commands."""
from __future__ import annotations

import math
import re

GROUPS = {"video0": "Основное видео", "image": "Изображение", "isp": "Сенсор",
          "audio": "Звук", "osd": "OSD камеры", "fpv": "FPV",
          "video1": "Второй поток", "jpeg": "Снимки"}
LABELS = {"codec": "Кодек", "size": "Разрешение", "fps": "Частота кадров",
          "bitrate": "Битрейт, кбит/с", "gopSize": "Интервал ключевого кадра",
          "enabled": "Включено", "mirror": "Зеркало", "flip": "Перевернуть",
          "rotate": "Поворот", "contrast": "Контраст", "saturation": "Насыщенность",
          "luminance": "Яркость", "hue": "Оттенок", "exposure": "Экспозиция",
          "antiFlicker": "Подавление мерцания", "noiseLevel": "Шумоподавление",
          "template": "Текст", "fontSize": "Размер текста", "font": "Шрифт",
          "position": "Положение", "profile": "Профиль", "rcMode": "Режим битрейта"}
LABELS.update(sliceUnits="Части кадра", qpDelta="Поправка качества", minQp="Минимальный QP",
              maxQp="Максимальный QP", maxBitrate="Предел битрейта", color="Цвет текста",
              outlineColor="Цвет контура", sensorConfig="Профиль сенсора",
              fontColor="Цвет шрифта", posX="Положение по X", posY="Положение по Y",
              samplingRate="Частота звука", volume="Громкость", gain="Усиление", mode="Режим")
_PRIVATE = re.compile(r"password|secret|token|private|credential|(^|[._])key($|[._])", re.I)

PATH_LABELS = {'osd.size': 'Размер текста', 'audio.srate': 'Частота звука, Гц',
               'audio.volume': 'Громкость микрофона', 'audio.enabled': 'Микрофон',
               'audio.outputEnabled': 'Динамик', 'audio.outputVolume': 'Громкость динамика',
               'audio.speakerPinInvert': 'Инверсия управления динамиком',
               'isp.iqServer': 'Сервер настройки сенсора', 'jpeg.qfactor': 'Качество снимков',
               'jpeg.rtsp': 'MJPEG по RTSP'}


def field_label(path, spec=None):
    name = path.split('.')[-1]
    return PATH_LABELS.get(path, LABELS.get(name, (spec or {}).get('title') or name))


def get_value(config, path):
    current = config
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def nested(values):
    result = {}
    for path, value in values.items():
        target = result
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return result


def wire_values(value):
    """Majestic's web form uses string leaves, preserving nested patch shape."""
    if isinstance(value, dict):
        return {key: wire_values(item) for key, item in value.items()}
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float):
        return str(value)
    return value


def fields(schema, config):
    """Only scalar camera controls advertised AND readable on this build."""
    result = {}

    def walk(node, prefix, depth=0):
        if depth > 5 or len(result) >= 256 or not isinstance(node, dict):
            return
        for key, spec in node.get("properties", {}).items():
            if not isinstance(spec, dict) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
                continue
            path = f"{prefix}.{key}" if prefix else key
            if _PRIVATE.search(path) or spec.get("writeOnly") or spec.get("format") == "password":
                continue
            if "properties" in spec:
                walk(spec, path, depth + 1)
            elif spec.get("type") in ("boolean", "integer", "number", "string"):
                try:
                    value = get_value(config, path)
                except KeyError:
                    continue  # An absent field is not permission to write a guessed default.
                result[path] = {**spec, "value": value}

    for group in GROUPS:
        node = schema.get("properties", {}).get(group)
        if node:
            walk(node, group)
    return result


def validate(spec, value):
    kind = spec["type"]
    valid = ((kind == "boolean" and type(value) is bool) or
             (kind == "integer" and type(value) is int) or
             (kind == "number" and type(value) in (int, float) and math.isfinite(value)) or
             (kind == "string" and isinstance(value, str)))
    if not valid:
        raise ValueError("Неверный тип значения")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError("Камера не поддерживает это значение")
    if kind in ("integer", "number"):
        if value < spec.get("minimum", -math.inf) or value > spec.get("maximum", math.inf):
            raise ValueError("Значение вне диапазона камеры")
    if kind == "string":
        if len(value) < spec.get("minLength", 0) or len(value) > min(spec.get("maxLength", 2048), 2048):
            raise ValueError("Неверная длина значения")
        # Patterns from firmware are not executed as unrestricted Python regexes.
        if "\x00" in value or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("Недопустимые символы")


def make_patch(schema, baseline, requested):
    available = fields(schema, baseline)
    changed = {}
    for path, value in requested.items():
        spec = available.get(path)
        if spec is None or spec.get("readOnly"):
            raise ValueError("Параметр недоступен для изменения: " + path)
        if value == spec["value"] and type(value) is type(spec["value"]):
            continue
        validate(spec, value)
        if value != spec["value"]:
            changed[path] = value
    return changed


def apply_checked(api, schema, baseline, requested, backup):
    """Read-before-write conflict check, minimal patch, effective-value readback.

    A timeout is ambiguous: inspect the device, do not silently repeat a write.
    Only our patch is backed up, never credentials or the full configuration.
    """
    changes = make_patch(schema, baseline, requested)
    if not changes:
        return api("GET", "/api/v1/config.json")
    before = api("GET", "/api/v1/config.json")
    if any(get_value(before, key) != get_value(baseline, key) for key in changes):
        raise ValueError("Настройки камеры изменились. Обновите их перед записью.")
    original = {key: get_value(before, key) for key in changes}
    backup(nested(original))
    error = None
    try:
        api("POST", "/api/v1/config", nested(changes))
    except (OSError, ValueError) as exc:
        error = exc
    try:
        after = api("GET", "/api/v1/config.json")
    except (OSError, ValueError) as exc:
        raise ValueError("Ответ камеры не получен. Настройки могли сохраниться — обновите их перед повторной записью.") from exc
    if all(get_value(after, key) == value for key, value in changes.items()):
        return after
    if all(get_value(after, key) == value for key, value in original.items()):
        raise ValueError("Камера не применила настройки") from error
    # Never overwrite unrelated or concurrently modified values with a backup.
    ours = {key: original[key] for key, value in changes.items() if get_value(after, key) == value}
    if ours:
        api("POST", "/api/v1/config", nested(ours))
        restored = api("GET", "/api/v1/config.json")
        if any(get_value(restored, key) != value for key, value in ours.items()):
            raise ValueError("Не удалось восстановить настройки. Проверьте камеру.")
    raise ValueError("Настройки применены не полностью. Восстановлены только изменения этой операции.")


def needs_reload(schema, config, changes):
    """Same firmware-declared reload classes as OpenIPC's settings page."""
    available = fields(schema, config)
    for path in changes:
        spec = available[path]
        mode = spec.get("x-reload")
        if not isinstance(mode, str) or not mode:
            if spec.get("x-live"):
                continue
        elif mode in ("none", "live") or any(mode.startswith(prefix) and len(mode) > len(prefix) for prefix in ("service:", "channel:")):
            continue
        return True
    return False
