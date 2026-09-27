"""Small local, asynchronous UI tones; never part of the media pipeline."""
import math
import struct
import time
import sys
import shutil
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QSoundEffect


class NativeVoice(QObject):
    """Use the independently verified player, outside Qt's audio mixer."""
    def __init__(self, name, parent=None):
        super().__init__(parent)
        from master.lifecycle_audio import LifecycleAudio
        self.player = LifecycleAudio(self)
        self.name = name
        self.volume = 100

    def setVolume(self, value):
        self.volume = round(value * 100)

    def play(self):
        self.stop()
        self.player.start(self.name, self.volume)

    def stop(self):
        self.player.cancel()

    def isPlaying(self):
        return self.player.active


class EventSounds(QObject):
    def __init__(self, root, enabled=True, parent=None):
        super().__init__(parent)
        self.enabled = enabled
        self.last = -30.0
        self.played = set()
        self.effects = {}
        self.voices = {}
        self.voice_enabled = False
        self.event_enabled = {}
        self.last_by_kind = {}
        from master.signal_alert import SignalAlert
        self.signal_alert = SignalAlert()
        folder = root / 'cache/sounds'
        folder.mkdir(parents=True, exist_ok=True)
        notes = {'startup': [(392, .18), (523.25, .22)],
                 'connected': [(523.25, .10)],
                 'warning': [(329.63, .14)], 'lost': [(329.63, .14), (261.63, .18)],
                 'record': [(440, .09)], 'saved': [(523.25, .08), (659.25, .10)]}
        for key in ('restored', 'receiver_lost', 'record_stopped', 'storage_full', 'settings_error', 'storage_lost', 'master_lost', 'master_restored'):
            notes[key] = notes['warning'] if key in ('receiver_lost', 'storage_full', 'settings_error', 'storage_lost', 'master_lost', 'master_restored') else notes['connected']
        for kind, sequence in notes.items():
            path = folder / (kind + '-v2.wav')
            if not path.exists():
                samples = bytearray()
                for frequency, duration in sequence:
                    count = int(duration * 24000)
                    for i in range(count):
                        envelope = math.sin(math.pi * i / count) ** 2
                        value = .35 * envelope * math.sin(2 * math.pi * frequency * i / 24000)
                        samples.extend(struct.pack('<h', int(value * 32767)))
                    samples.extend(b'\0\0' * 720)
                with wave.open(str(path), 'wb') as output:
                    output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                    output.writeframes(samples)
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setVolume(.08)
            self.effects[kind] = effect

        for kind in ('warning', 'connected', 'record', 'saved', 'lost', 'restored', 'receiver_lost', 'record_stopped', 'storage_full', 'settings_error', 'storage_lost', 'master_lost', 'master_restored'):
            path = Path(__file__).parent / 'assets' / 'voice' / (kind + '.wav')
            if path.is_file():
                if sys.platform == 'linux' and shutil.which('paplay'):
                    effect = NativeVoice(kind, self)
                else:
                    effect = QSoundEffect(self)
                    effect.setSource(QUrl.fromLocalFile(str(path)))
                effect.setVolume(.16)
                self.voices[kind] = effect

    def set_volume(self, percent):
        for effect in self.effects.values():
            effect.setVolume(max(0, min(60, percent)) / 100)

    def set_voice_volume(self, percent):
        for effect in self.voices.values():
            effect.setVolume(max(0, min(100, percent)) / 100)

    def preview(self):
        (self.voices.get('connected', self.effects['startup']) if self.voice_enabled else self.effects['startup']).play()

    def play(self, kind):
        now = time.monotonic()
        if not self.enabled or not self.event_enabled.get(kind, True) or kind not in self.effects:
            return
        if now - self.last_by_kind.get(kind, -30) < (20 if kind in ('receiver_lost', 'storage_full', 'settings_error', 'storage_lost') else 3):
            return
        if kind == 'record_stopped' and any(now - self.last_by_kind.get(key, -30) < 3 for key in ('storage_lost', 'storage_full', 'warning')):
            return
        if kind in ('startup', 'connected') and kind in self.played:
            return
        # No speech queue: stale announcements must not accumulate.
        for effect in [*self.effects.values(), *self.voices.values()]:
            if effect.isPlaying():
                effect.stop()
        self.played.add(kind)
        self.last_by_kind[kind] = now
        self.last = now
        effect = self.voices.get(kind) if self.voice_enabled else None
        (effect or self.effects[kind]).play()

    def observe_signal(self, state, running, suppress=False):
        was_lost = self.signal_alert.announced
        if self.signal_alert.update(state, running, time.monotonic(), suppress):
            self.play('lost')
        elif was_lost and not self.signal_alert.announced and running and not suppress and state.get('phase') == 'video' and (state.get('mbps') or 0) > .01:
            self.play('restored')

    def notify_event(self, text):
        if text.startswith(('Мастер отключён', 'Связь с мастером потеряна')):
            self.play('master_lost')
        elif text == 'Связь с мастером восстановлена':
            self.play('master_restored')
        elif text == 'Запись остановлена: накопитель отключён':
            self.play('storage_lost')
        elif text == 'Запись остановлена: накопитель заполнен':
            self.play('storage_full')
        elif text == 'Запись остановлена' or text.startswith('Запись остановлена:'):
            self.play('record_stopped')
        elif text.startswith(('RX1 отключён', 'RX2 отключён')):
            self.play('receiver_lost')
        elif text.startswith('Ошибка записи'):
            self.play('warning')
        elif text == 'Запись начата':
            self.play('record')
        elif text.startswith('Запись сохранена:'):
            if time.monotonic() - self.last_by_kind.get('record_stopped', -30) >= 3:
                self.play('saved')
        elif text == 'Видео получено':
            self.play('connected')
