"""Presentation of observed hardware; discovery never implies control access."""
from dataclasses import dataclass
import time

from shared.models import ModuleState


@dataclass(frozen=True)
class LocalReceiverStatus:
    title: str
    tone: str
    mode: str
    usb_count: int
    receiving_count: int
    video: str
    tx: str


def local_receiver_status(devices, state, running, mode, now=None):
    now = time.monotonic() if now is None else now
    local = running and mode == 'local'
    receiving = sum(0 <= now - row.get('last_frame_monotonic', 0) < 2
                    for row in state.get('receivers', []) if local)
    phase = state.get('phase', 'idle')
    count = len(devices)
    title, tone, signal = 'Ожидание USB', 'offline', 'offline'
    if count:
        title, tone, signal = 'Готов к запуску', 'warning', 'ready'
    if local:
        title, tone, signal = ('Приём', 'ready', 'receiving') if receiving else ('Поиск сигнала', 'warning', 'waiting')
        if phase in ('starting', 'recovering'):
            title, tone, signal = 'Инициализация' if phase == 'starting' else 'Восстановление', 'warning', 'initializing'
        elif receiving == 1:
            title, tone = 'Приём · один RX', 'warning'
    video = f"{state.get('width', '—')} × {state.get('height', '—')}" if local and phase == 'video' and receiving else 'Ожидание'
    control = state.get('control', {}) if local else {}
    fresh_reply = 0 <= now - control.get('last_reply_monotonic', 0) < 3
    tx = (f"Ответ · {control['rtt_ms']:.0f} мс" if fresh_reply and control.get('state') == 'connected'
          and isinstance(control.get('rtt_ms'), (int, float)) else
          'Нет ответа' if local and control.get('state') in ('connected', 'waiting') else
          'Запуск' if control.get('state') in ('starting', 'retrying') else
          'Ошибка' if control.get('state') == 'error' else 'Выключен')
    return LocalReceiverStatus(title, tone, signal, count, receiving, video, tx)


def discovered_status(module):
    if module.state is ModuleState.UNREACHABLE:
        return 'Нет связи', 'offline', 'offline'
    # The current UDP protocol has no authenticated readiness message.
    return 'В сети · приём не подтверждён', 'warning', 'waiting'
