"""Bounded event delivery: collapse superseded states, keep failures visible."""
from collections import OrderedDict


def category(text):
    for key, words in (
        ('record', ('Запись начата', 'Запись остановлена', 'Запись сохранена')),
        ('broadcast', ('Трансляция включена', 'Трансляция выключена')),
        ('camera', ('Камера найдена', 'Камера подключается', 'Камера подключена', 'Видео получено')),
        ('signal', ('Видеосигнал потерян', 'Видеосигнал восстановлен')),
        ('master', ('Связь с мастером', 'Мастер отключён')),
        ('rx', ('Подключены RX', 'RX1 подключён', 'RX2 подключён', 'RX3 подключён')),
    ):
        if text.startswith(words):
            return key
    return text


def urgent(text):
    return any(word in text.lower() for word in ('ошибка', 'не удалось', 'потерян', 'отключён', 'заполнен'))


class NotificationQueue:
    def __init__(self):
        self.pending = OrderedDict()
        self.recent = {}
        self.last_by_category = {}
        self.visible_category = None
        self.visible_until = 0

    def push(self, text, now):
        key = category(text)
        self.recent = {s: t for s, t in self.recent.items() if now-t < 45}
        if text in self.recent and self.last_by_category.get(key) == text:
            return False
        self.recent[text] = now
        self.last_by_category[key] = text
        if len(self.last_by_category) > 128:
            self.last_by_category = {category(s): s for s in self.recent}
        self.pending[key] = (text, now)
        if len(self.pending) > 8:
            stale = next((k for k, (s, _) in self.pending.items() if not urgent(s)), next(iter(self.pending)))
            self.pending.pop(stale)
        return True

    def take(self, now):
        self.pending = OrderedDict((k, v) for k, v in self.pending.items()
                                   if now-v[1] < (30 if urgent(v[0]) else 12))
        if not self.pending:
            return None
        priority = next((k for k, (s, _) in self.pending.items() if urgent(s)), None)
        replacement = self.visible_category if self.visible_category in self.pending else None
        if now < self.visible_until and priority is None and replacement is None:
            return None
        key = priority or replacement or next(iter(self.pending))
        text, _ = self.pending.pop(key)
        self.visible_category, self.visible_until = key, now+4.0
        return text
