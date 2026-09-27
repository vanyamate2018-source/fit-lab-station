"""Process supervision and RTP transport for the master; UI only observes signals."""
from __future__ import annotations

import ipaddress
import json
import struct
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QUdpSocket

from master.media_env import media_environment
from shared.rtp import parse as parse_rtp, SequenceTracker


class StationSession(QObject):
    frame = Signal(QImage)
    changed = Signal(dict)
    message = Signal(str)
    diagnostic = Signal(str)
    cameraSelected = Signal(dict)
    camerasDiscovered = Signal(list)
    cameraChoiceRequired = Signal()

    def __init__(self, data_root: Path, parent=None):
        super().__init__(parent)
        self.root = data_root
        self.radio = QProcess(self)
        self.scanner = QProcess(self)
        self.scanner.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.scanner.readyReadStandardOutput.connect(self._discovery_output)
        self.discovery_buffer = b''
        self.discovered = []
        self.pending_start = None
        self.media = QProcess(self)
        self.audio = QProcess(self)
        self.audio_port = 0
        self.audio_volume = 35
        import os
        self.audio_muted = False
        self.audio_buffer = b''
        self.audio_retry_at = 0.0
        self.last_audio_log = 0.0
        self.audio.readyReadStandardOutput.connect(self._audio_events)
        self.audio.started.connect(self._audio_gain)
        self.recorder = QProcess(self)
        self.streamer = QProcess(self)
        self.stream_port = 0
        self.stream_buffer = b""
        self.stream_wanted = False
        from master.hotspot import Hotspot
        self.hotspot = Hotspot(self)
        self.hotspot.ready.connect(self._hotspot_ready)
        self.hotspot.error.connect(self._hotspot_error)
        self.hotspot_mode = None
        self.record_port = 0
        self.record_audio_port = 0
        self.record_path = None
        self.record_buffer = b""
        from master.rtp_relay import RtpRelay
        self.udp = RtpRelay()
        self.relay_restarts = 0
        self.relay_integrity = None
        self.buffer = bytearray()
        self.frame_memory = None
        self.video_window_handle = 0
        self.video_rectangle = (640, 360)
        self.native_video_failed = False
        from shared.media_activity import MediaActivity
        self.media_activity = MediaActivity(data_root)
        self.decoder_restart = False
        self.last_decoder_restart = 0.0
        self.media_options = []
        self.stderr = b""
        self.radio_buffer = b""
        self.state: dict = {"phase": "idle", "rtp_packets": 0, "mbps": 0.0}
        self.last_packet = self.last_frame = 0.0
        self.last_decoder_restart = time.monotonic()
        self.bytes = self.previous_bytes = 0
        self.previous_time = time.monotonic()
        self.forward: tuple[str, int] | None = None
        self.running = False
        self.camera_search = None
        self.search_blocked = False
        self.handover = None
        self.seen_cameras = {}
        self.selection_pinned = False
        self.last_log = 0.0
        self.receiver_notice_pending = False
        from shared.link_health import LinkHealth
        self.health = LinkHealth()
        self.last_health_log = 0.0
        self.mode = "local"
        self.peer: str | None = None
        self.rtp_stats = SequenceTracker()
        self.rtp_frame_timestamps = set()
        self.media_port = 0
        self.radio.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.radio.readyReadStandardOutput.connect(self._radio_output)
        self.radio.finished.connect(self._radio_finished)
        self.radio.errorOccurred.connect(lambda _: self._error(self.radio.errorString()))
        self.media.readyReadStandardOutput.connect(self._frames)
        self.media.readyReadStandardError.connect(self._media_events)
        self.media.finished.connect(self._media_finished)
        self.media.errorOccurred.connect(self._decoder_error)
        self.recorder.readyReadStandardOutput.connect(self._record_events)
        self.recorder.finished.connect(self._record_finished)
        self.recorder.errorOccurred.connect(lambda _: self._optional_error("recording", self.recorder))
        self.streamer.readyReadStandardOutput.connect(self._stream_events)
        self.streamer.finished.connect(self._stream_finished)
        self.streamer.errorOccurred.connect(lambda _: self._optional_error("streaming", self.streamer))
        self.packet_timer = QTimer(self)
        self.packet_timer.setInterval(50)
        self.packet_timer.timeout.connect(self._packets)
        self.packet_timer.start()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def start(self, mode="local", duration=0, latency=40, test=False, codec="h265", channel=161, width=20, recovery="keyframe", control=False, decoder_mode='lowlatency', _search=None, profile_identity=None, auto_select=False, pin_selection=False, profile_tuning=None, retune=False):
        options = dict(mode=mode, duration=duration, latency=latency, test=test, codec=codec, channel=channel,
                       width=width, recovery=recovery, control=control, decoder_mode=decoder_mode, _search=_search,
                       profile_identity=profile_identity, auto_select=auto_select, pin_selection=pin_selection,
                       profile_tuning=profile_tuning)
        if auto_select and mode == 'local' and not test and not self.running:
            self._resolve_auto_start(options)
            return
        if self.scanner.state() != QProcess.ProcessState.NotRunning:
            self.pending_start = options
            self.scanner.terminate()
            deadline = time.monotonic() + 10
            def wait_scanner():
                if self.pending_start is not options:
                    return
                if self.scanner.state() != QProcess.ProcessState.NotRunning:
                    if time.monotonic() < deadline:
                        QTimer.singleShot(100, wait_scanner)
                        return
                    self.pending_start = None
                    self._error('Поиск камер ещё останавливается · повторите запуск')
                    return
                self.pending_start = None
                self.start(**options)
            QTimer.singleShot(100, wait_scanner)
            return
        if self.running or any(p.state() != QProcess.ProcessState.NotRunning for p in (self.radio, self.media)):
            return
        if profile_identity:
            from shared.pairing_store import PairingStore
            try:
                profile = PairingStore(self.root).select_known(profile_identity, profile_tuning)
                config = profile['receiver_config']
                channel, width = config['radio_channel'], config['radio_width']
                codec = config.get('codec', 'H.265').lower().replace('.', '')
                self.cameraSelected.emit(profile)
                self.diagnostic.emit(('Ручной выбор' if pin_selection else 'Автовыбор') +
                                     ' · ' + profile.get('camera_label', 'Сохранённая камера'))
            except (OSError, ValueError, KeyError) as exc:
                self._error(str(exc))
                return
        self.mode = mode
        self.selection_pinned = pin_selection
        self.selected_codec = codec
        from shared.radio_settings import receiver_settings
        tuning = receiver_settings(channel, width)
        self.start_options = dict(mode=mode, duration=duration, latency=latency, test=test, codec=codec,
                                  channel=channel, width=width, recovery=recovery, control=control, decoder_mode=decoder_mode)
        self.camera_search = _search
        import os
        if self.camera_search is None and mode in ('local', 'lan') and not test and not os.environ.get('FIT_LAB_PAIRING_ID'):
            from shared.pairing_store import PairingStore
            from master.camera_search import CameraSearch
            store = PairingStore(self.root)
            active = store.read(store.active_path) or {}
            self.camera_search = CameraSearch(store.profiles(), active.get('identity'), tuning, time.monotonic())
        if self.camera_search:
            self.camera_search.tuned(time.monotonic())
        self.buffer.clear()
        self.stderr = self.radio_buffer = b""
        self.bytes = self.previous_bytes = 0
        self.previous_time = time.monotonic()
        self.last_packet = self.last_frame = 0.0
        self.last_decoder_restart = time.monotonic()
        self.peer = None
        self.relay_restarts = 0
        self.relay_integrity = None
        self.rtp_stats = SequenceTracker()
        self.rtp_frame_timestamps.clear()
        self.state = {"phase": "starting", "rtp_packets": 0, "mbps": 0.0, "mode": mode, "radio_tuning": tuning}
        self.state['selected_camera'] = self.camera_search.active if self.camera_search else profile_identity
        from shared.link_health import LinkHealth
        self.health = LinkHealth()
        self.last_health_log = time.monotonic()
        listen_port = 15600 if mode == "local" else 5600
        address = '127.0.0.1' if mode == "local" else '0.0.0.0'
        if not self.udp.bind(address, listen_port):
            self._error(f"UDP {listen_port}: {self.udp.errorString()}")
            return
        probe = QUdpSocket()
        if not probe.bind(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0):
            self.udp.close()
            self._error("Не удалось выделить порт декодера")
            return
        self.media_port = probe.localPort()
        probe.close()
        env = media_environment(self.root)
        env.update(FIT_LAB_DATA_ROOT=str(self.root), FIT_LAB_ROOT=str(self.root.parent),
                   FIT_LAB_VIEW_SECONDS=str(duration), FIT_LAB_RTP_PORT=str(listen_port),
                   FIT_LAB_RADIO_CHANNEL=str(channel), FIT_LAB_RADIO_WIDTH=str(width),
                   FIT_LAB_CONTROL='1' if control else '0', FIT_LAB_RETUNE='1' if retune else '0',
                   FIT_LAB_FOLLOW_RECEIVER='1' if _search is None else '0')
        qenv = QProcessEnvironment()
        for name, value in env.items():
            qenv.insert(name, value)
        for proc in (self.radio, self.media):
            proc.setProcessEnvironment(qenv)
            proc.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.running = True
        self.state["realtime_activity"] = self.media_activity.start()
        self.media_options = ["-m", "master.media_worker", "--port", str(self.media_port), "--latency", str(latency),
                              "--codec", codec, "--frame-timestamps", "--recovery", recovery, '--decoder-mode', decoder_mode]
        if test:
            self.media_options.append("--test")
        self._launch_decoder()
        if not self.running:
            return
        if mode == "local" and not test and os.environ.get("FIT_LAB_EMBEDDED_RECEIVER") == "1":
            self.radio.start(sys.executable, ["-u", "-m", "master.lan_receiver"])
        elif mode == "local" and not test:
            self.radio.start(sys.executable, ["-u", "-m", "receiver.dual_radio"])
        elif mode == 'lan' and not test:
            self.radio.start(sys.executable, ['-u', '-m', 'master.lan_receiver'])
        self.state["synthetic"] = test
        self.message.emit("Запуск локального приёмника" if mode == "local" else f"Ожидание RTP/{codec.upper()} по LAN · UDP 5600")
        self.changed.emit(dict(self.state))

    def _launch_decoder(self):
        from multiprocessing.shared_memory import SharedMemory
        self._release_frame_memory()
        if self.video_window_handle and not self.native_video_failed and self.start_options.get('decoder_mode') == 'hardware':
            self.buffer.clear()
            self.stderr = b''
            self.media.start(sys.executable, self.media_options + ['--window-handle', str(self.video_window_handle),
                '--window-width', str(self.video_rectangle[0]), '--window-height', str(self.video_rectangle[1])])
            return
        try:
            self.frame_memory = SharedMemory(create=True, size=(4096 * 4 + 256) * 2160)
        except OSError:
            self._error("Не удалось выделить память для видео")
            return
        self.buffer.clear()
        self.stderr = b""
        self.media.start(sys.executable, self.media_options + ["--frame-memory", self.frame_memory.name])

    def restart_decoder(self, codec=None):
        if not self.running:
            return
        if codec is not None:
            if codec not in ("h264", "h265"):
                raise ValueError("Неподдерживаемый видеокодек")
            self.selected_codec = codec
            self.start_options['codec'] = codec
            self.media_options[self.media_options.index("--codec") + 1] = codec
        if self.decoder_restart:
            return
        self.decoder_restart = True
        self.last_decoder_restart = time.monotonic()
        self.last_frame = 0
        self.state.update(phase="decoding", fps=0, decoder_restarts=self.state.get("decoder_restarts", 0) + 1)
        process_id = self.media.processId()
        self.media.terminate()
        QTimer.singleShot(3000, lambda: self.media.kill() if self.decoder_restart and self.media.processId() == process_id else None)
        self.changed.emit(dict(self.state))

    def stop(self, _handover=False):
        self.audio_port = 0
        if self.audio.state() != QProcess.ProcessState.NotRunning:
            self.audio.terminate()
        if not _handover:
            self.pending_start = None
            if self.scanner.state() != QProcess.ProcessState.NotRunning:
                self.scanner.terminate()
            self.handover = None
            self.camera_search = None
            self.selection_pinned = False
        if not self.running:
            self.state.update(phase='stopped', camera_search='stopped')
            self.changed.emit(dict(self.state))
            return
        self.running = False
        self.decoder_restart = False
        self.media_activity.close()
        self.stop_recording()
        self.stop_streaming()
        self.udp.close()
        for proc in (self.radio, self.media):
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.terminate()
        self.state.update(phase="stopped", mbps=0.0)
        self.message.emit("Приём остановлен")
        self.changed.emit(dict(self.state))

    def close(self):
        self.stop()
        self.hotspot.close()
        for proc in (self.radio, self.media, self.recorder, self.streamer, self.scanner, self.audio):
            if not proc.waitForFinished(12000):
                proc.kill()
                proc.waitForFinished(2000)
        self._release_frame_memory()

    def _release_frame_memory(self):
        if self.frame_memory is not None:
            self.frame_memory.close()
            self.frame_memory.unlink()
            self.frame_memory = None

    def discover_cameras(self):
        if self.running or self.handover or self.pending_start or self.scanner.state() != QProcess.ProcessState.NotRunning:
            return
        if self.radio.state() != QProcess.ProcessState.NotRunning:
            return
        from shared.pairing_store import PairingStore
        if not PairingStore(self.root).profiles() or PairingStore(self.root).pending():
            return
        env = media_environment(self.root)
        env.update(FIT_LAB_DATA_ROOT=str(self.root), FIT_LAB_ROOT=str(self.root.parent))
        qenv = QProcessEnvironment()
        for name, value in env.items():
            qenv.insert(name, value)
        self.scanner.setProcessEnvironment(qenv)
        self.scanner.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.discovery_buffer = b''
        import os
        module = 'receiver.embedded_discovery' if os.environ.get('FIT_LAB_EMBEDDED_RECEIVER') == '1' else 'receiver.camera_discovery'
        self.scanner.start(sys.executable, ['-u', '-m', module])

    def _resolve_auto_start(self, options):
        """Finish a receive-only observation before stopping discovery to open video."""
        if self.pending_start or self.handover:
            return
        self.discover_cameras()
        self.pending_start = options
        started = time.monotonic()
        self.state.update(phase='searching', camera_search='selecting')
        self.changed.emit(dict(self.state))

        def resolve():
            if self.pending_start is not options:
                return  # Stop cancels both discovery and the deferred launch.
            from master.camera_search import available_cameras
            now = time.monotonic()
            available = available_cameras(self.discovered, now)
            # Give both receivers time to report: a late second camera must not
            # be silently ignored because RX1 initialized first.
            waiting = self.scanner.state() != QProcess.ProcessState.NotRunning
            initializing = any(r.get('connection') in ('initializing', 'preparing', 'recovering')
                               for r in self.state.get('receivers', []))
            if waiting and (now - started < 2 or ((not available or initializing) and now - started < 12)):
                QTimer.singleShot(200, resolve)
                return
            self.pending_start = None
            if len(available) > 1:
                self.state.update(phase='idle', camera_search='choose')
                self.changed.emit(dict(self.state))
                self.message.emit('В эфире несколько камер · выберите нужную')
                self.cameraChoiceRequired.emit()
                return
            options['auto_select'] = False
            if available:
                identity = next(iter(available))
                options['profile_identity'] = identity
                tuning = available[identity].get('tuning', {})
                if 'channel' in tuning and 'width' in tuning:
                    options['profile_tuning'] = {key: tuning[key] for key in ('channel', 'width')}
            self.start(**options)

        QTimer.singleShot(0, resolve)

    def _discovery_output(self):
        self.discovery_buffer += bytes(self.scanner.readAllStandardOutput())
        lines = self.discovery_buffer.split(b'\n')
        self.discovery_buffer = lines.pop()[-65536:]
        for line in lines:
            if not line.startswith(b'FITLAB_EVENT '):
                continue
            try:
                event = json.loads(line[13:])
            except (ValueError, UnicodeDecodeError):
                continue
            if event.get('state') == 'camera_discovery':
                self.discovered = event['cameras']
                for camera in self.discovered:
                    self.seen_cameras[camera['identity']] = camera['last_seen']
                self.camerasDiscovered.emit(self.discovered)
                self.state['receivers'] = event['receivers']
                self.state['camera_search'] = 'listening'
            elif event.get('error'):
                self.message.emit(event['error'])

    def _hotspot_ready(self, host):
        if not self.hotspot_mode:
            self.hotspot.stop()
            return
        try:
            self.start_streaming(host, self.hotspot_mode)
        except ValueError as exc:
            self._hotspot_error(str(exc))

    def _hotspot_error(self, message):
        self.stop_streaming()
        self.state['streaming'] = 'error'
        self.message.emit(message)
        self.changed.emit(dict(self.state))

    def start_streaming(self, host, mode="rtsp"):
        if host == 'fitlab-hotspot':
            if not self.running or time.monotonic() - self.last_packet > 2:
                raise ValueError('Сначала дождитесь видеопотока')
            self.hotspot_mode = mode
            self.hotspot.start()
            self.state.update(streaming='starting', stream_host=None)
            self.changed.emit(dict(self.state))
            return
        if mode not in ("web", "rtsp"):
            raise ValueError("Неизвестный формат трансляции")
        from master.viewer_network import is_lan_address, local_viewer_networks, local_hotspot_issue
        if not is_lan_address(host):
            raise ValueError("Выберите адрес локальной сети")
        networks = local_viewer_networks()
        if any(item.address == host and item.kind == 'hotspot' for item in networks):
            issue = local_hotspot_issue(networks)
            if issue:
                raise ValueError(issue)
        address = ipaddress.IPv4Address(host)
        if not self.running or time.monotonic() - self.last_packet > 2:
            raise ValueError("Сначала дождитесь видеопотока")
        if self.streamer.state() != QProcess.ProcessState.NotRunning:
            return
        probe = QUdpSocket()
        if not probe.bind(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0):
            raise ValueError("Не удалось подготовить трансляцию")
        self.stream_port = probe.localPort()
        probe.close()
        qenv = QProcessEnvironment()
        for name, value in media_environment(self.root).items():
            qenv.insert(name, value)
        self.streamer.setProcessEnvironment(qenv)
        self.streamer.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.stream_buffer = b""
        self.stream_wanted = True
        self.state.update(streaming="starting", stream_clients=0, stream_host=str(address), stream_signal=False)
        self.state["stream_mode"] = mode
        worker = "master.web_stream_worker" if mode == "web" else "master.stream_worker"
        self.streamer.start(sys.executable, ["-m", worker, "--host", str(address),
                                            "--input-port", str(self.stream_port), "--codec", self.selected_codec] +
                            (["--external-viewer"] if mode == "web" and getattr(self, "external_viewer", False) else []))

    def stop_streaming(self):
        self.hotspot_mode = None
        self.hotspot.stop()
        self.stream_wanted = False
        self.stream_port = 0
        self.state.update(stream_url="", stream_clients=0)
        if self.streamer.state() != QProcess.ProcessState.NotRunning:
            self.state["streaming"] = "stopping"
            self.streamer.terminate()
        else:
            self.state["streaming"] = "stopped"

    def _stream_events(self):
        self.stream_buffer += bytes(self.streamer.readAllStandardOutput())
        lines = self.stream_buffer.split(b"\n")
        self.stream_buffer = lines.pop()[-8192:]
        for line in lines:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if not self.stream_wanted or not isinstance(data, dict):
                continue
            kind = data.get("state")
            if kind == "error":
                self.state["streaming"] = "error"
                self.message.emit("Ошибка трансляции: " + data.get("error", ""))
            elif kind == "streaming":
                self.state.update(streaming="streaming", stream_url=data.get("url", ""), stream_signal=True)
                self.message.emit("Трансляция включена")
            elif kind == "clients":
                self.state["stream_clients"] = max(0, int(data.get("count", 0)))
            elif kind == "signal":
                self.state['stream_signal'] = bool(data.get('ready'))

    def _stream_finished(self, code, _):
        self.hotspot_mode = None
        self.hotspot.stop()
        self._stream_events()
        self.stream_port = 0
        failed = self.stream_wanted and (code != 0 or self.state.get("streaming") == "error")
        self.stream_wanted = False
        self.state.update(streaming="error" if failed else "stopped", stream_url="", stream_clients=0)

    def start_recording(self, directory: Path):
        from shared.recording_storage import validate_recording_directory
        validate_recording_directory(directory)
        if not self.running or time.monotonic() - self.last_packet > 2:
            raise ValueError("Сначала дождитесь видеопотока")
        if self.recorder.state() != QProcess.ProcessState.NotRunning:
            raise ValueError("Предыдущая запись ещё завершается")
        if not directory.is_dir() or shutil.disk_usage(directory).free < 300 * 1024**2:
            raise ValueError("На накопителе недостаточно места")
        path = directory / (time.strftime("FIT-LAB-%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000000:06d}.mkv")
        # Reserve a new filename; never overwrite a recording.
        with path.open("xb"):
            pass
        probe = QUdpSocket()
        if not probe.bind(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0):
            raise ValueError("Не удалось выделить порт записи")
        self.record_port = probe.localPort()
        probe.close()
        self.record_audio_port = 0
        if time.monotonic() - self.udp.snapshot().get('last_audio_packet', 0) < 2:
            audio_probe = QUdpSocket()
            if audio_probe.bind(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0):
                self.record_audio_port = audio_probe.localPort()
                audio_probe.close()
        env = QProcessEnvironment()
        for name, value in media_environment(self.root).items():
            env.insert(name, value)
        self.recorder.setProcessEnvironment(env)
        self.recorder.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.record_path = path
        self.record_buffer = b""
        self.state["recording"] = "starting"
        self.recorder.start(sys.executable, ["-m", "master.record_worker", "--port", str(self.record_port),
                                            "--codec", self.selected_codec, "--output", str(path),
                                            "--audio-port", str(self.record_audio_port)])

    def stop_recording(self):
        self.record_port = 0
        self.record_audio_port = 0
        if self.recorder.state() != QProcess.ProcessState.NotRunning:
            if self.state.get("recording") != "finishing":
                self.message.emit("Запись остановлена")
            self.state["recording"] = "finishing"
            self.recorder.terminate()

    def _record_events(self):
        self.record_buffer += bytes(self.recorder.readAllStandardOutput())
        lines = self.record_buffer.split(b"\n")
        self.record_buffer = lines.pop()[-8192:]
        for line in lines:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            state = data.get("state")
            if state == "audio_ended":
                self.state["recording_audio"] = "ended"
                continue
            self.state["recording"] = state
            if state == "recording":
                self.message.emit("Запись начата")
            elif state == "saved":
                self.message.emit("Запись сохранена: " + str(self.record_path))
            elif state == "error":
                self.message.emit("Ошибка записи: " + data.get("error", ""))

    def _record_finished(self, code, _):
        self._record_events()
        self.record_port = 0
        self.record_audio_port = 0
        self.state["recording"] = "error" if code else "stopped"
        if code and self.record_path:
            try:
                if self.record_path.stat().st_size == 0:
                    self.record_path.unlink()
            except OSError:
                pass

    def set_forward(self, host: str | None, port=5600):
        if host is None:
            self.forward = None
            self.state["forward"] = None
            return
        address = ipaddress.IPv4Address(host.strip())
        if not address.is_private or address.is_multicast or address.is_unspecified or address.is_loopback:
            raise ValueError("Укажите локальный IPv4-адрес другого устройства")
        if not 1024 <= port <= 65535:
            raise ValueError("Порт должен быть от 1024 до 65535")
        self.forward = str(address), port
        self.state["forward"] = f"{address}:{port}"

    def _packets(self):
        if not self.running:
            return
        self.udp.configure(video=self.media_port, audio=self.audio_port,
                           record=self.record_port, stream=self.stream_port, forward=self.forward,
                           record_audio=self.record_audio_port)
        snapshot = self.udp.snapshot()
        now = time.monotonic()
        if snapshot['audio_packets'] and not self.audio_muted and self.audio.state() == QProcess.ProcessState.NotRunning and now >= self.audio_retry_at:
            self._start_audio()
        from master.media_recovery import recovery_reason
        reason = recovery_reason(now, self.last_packet, snapshot['last_packet'],
                                 self.last_frame, self.last_decoder_restart,
                                 snapshot['restarts'] != self.relay_restarts)
        if reason:
            self.state['decoder_recovery_reason'] = reason
            self.restart_decoder()
        self.relay_restarts = snapshot['restarts']
        self.relay_integrity = snapshot['integrity']
        self.rtp_frame_timestamps.update(snapshot['frames'])
        self.last_packet = snapshot['last_packet']
        self.peer = snapshot['peer']
        self.bytes = snapshot['bytes']
        self.state.update(rtp_packets=snapshot['packets'], audio_packets=snapshot['audio_packets'], peer=self.peer)
        if snapshot['forward_error']:
            self.set_forward(None)
            self.message.emit(snapshot['forward_error'])

    def _start_audio(self):
        probe = QUdpSocket(self)
        if not probe.bind(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0):
            return
        self.audio_port = probe.localPort()
        probe.close()
        probe.deleteLater()
        environment = QProcessEnvironment()
        for key, value in media_environment(self.root).items():
            environment.insert(key, value)
        self.audio.setProcessEnvironment(environment)
        self.audio.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.audio_buffer = b''
        self.audio_retry_at = time.monotonic() + 10
        self.audio.start(sys.executable, ['-u', '-m', 'master.audio_worker', '--port', str(self.audio_port)])

    def set_audio(self, volume, muted):
        self.audio_volume = max(0, min(100, int(volume)))
        self.audio_muted = bool(muted)
        self._audio_gain()

    def _audio_gain(self):
        if self.audio.state() == QProcess.ProcessState.Running:
            self.audio.write((json.dumps({'volume': self.audio_volume / 100,
                                         'muted': self.audio_muted}) + '\n').encode())

    def _audio_events(self):
        self.audio_buffer += bytes(self.audio.readAllStandardOutput())
        while b'\n' in self.audio_buffer:
            line, self.audio_buffer = self.audio_buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            self.state['audio'] = event
            self.state['audio']['transport'] = 'wfb_rtp' if self.state.get('mode') == 'local' else 'lan_rtp'
            if time.monotonic() - self.last_audio_log >= 10:
                from master.diagnostics import append_event
                append_event(self.root, {'time': time.time(), 'operation': 'camera_audio',
                    **self.state['audio'], 'volume_percent': self.audio_volume})
                self.last_audio_log = time.monotonic()

    def _frames(self):
        self.buffer.extend(bytes(self.media.readAllStandardOutput()))
        if self.frame_memory is not None:
            while len(self.buffer) >= 24:
                width, height, stride, length, sent_at = struct.unpack_from(">IIIIQ", self.buffer)
                del self.buffer[:24]
                if not (0 < width <= 4096 and 0 < height <= 2160 and width * 4 <= stride <= width * 4 + 256
                        and length == stride * height and length <= self.frame_memory.size):
                    self._error("Неверный формат кадра от декодера")
                    self.media.kill()
                    self.buffer.clear()
                    return
                age_ms = max(0, time.monotonic_ns() - sent_at) / 1e6
                # The worker cannot overwrite this memory until the ACK.
                # Copy only a fresh frame; this also recovers from a UI stall
                # without replaying the stalled interval at normal speed.
                if age_ms < 150 and self.running:
                    # Decoder pixels are opaque. RGBX avoids per-paint alpha
                    # blending; one owned copy releases the shared slot safely.
                    frame = QImage(self.frame_memory.buf, width, height, stride, QImage.Format.Format_RGBX8888).copy()
                    self.last_frame = time.monotonic()
                    self.state["decoder_to_ui_ms"] = round(age_ms, 2)
                    self.frame.emit(frame)
                else:
                    self.state["stale_display_frames"] = self.state.get("stale_display_frames", 0) + 1
                self.media.write(b"\x01")
            return
        latest = None
        consumed = 0
        while len(self.buffer) - consumed >= 24:
            width, height, stride, length, sent_at = struct.unpack_from(">IIIIQ", self.buffer, consumed)
            if not (0 < width <= 4096 and 0 < height <= 2160 and width * 4 <= stride <= width * 4 + 256 and length == stride * height):
                self._error("Неверный формат кадра от декодера")
                self.media.kill()
                self.buffer.clear()
                return
            if len(self.buffer) - consumed < 24 + length:
                break
            latest = (consumed + 24, width, height, stride, length, sent_at)
            consumed += 24 + length
        if latest is not None:
            offset, width, height, stride, length, sent_at = latest
            raw = bytes(self.buffer[offset:offset + length])
            latest = QImage(raw, width, height, stride, QImage.Format.Format_RGBX8888).copy()
            del self.buffer[:consumed]
            age_ms = max(0, time.monotonic_ns() - sent_at) / 1e6
            if age_ms >= 150 or not self.running:
                self.state['stale_display_frames'] = self.state.get('stale_display_frames', 0) + 1
                return
            self.last_frame = time.monotonic()
            self.state["decoder_to_ui_ms"] = round(age_ms, 2)
            self.frame.emit(latest)

    def _media_events(self):
        chunk = bytes(self.media.readAllStandardError())
        log = self.root / 'logs/decoder-console.log'
        try:
            if log.exists() and log.stat().st_size > 2 * 1024 * 1024:
                log.replace(log.with_suffix('.previous.log'))
            with log.open('ab') as output:
                output.write(chunk)
        except OSError:
            pass
        self.stderr += chunk
        lines = self.stderr.split(b"\n")
        self.stderr = lines.pop()[-8192:]
        for line in lines:
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if event.get("state") == "error":
                if self.video_window_handle and not self.native_video_failed:
                    self.native_video_failed = True
                    self.state.pop('frame_transport', None)
                    self.message.emit('Переключение на совместимый видеовывод')
                    self.restart_decoder()
                    continue
                self._error(event.get("error", "Ошибка декодера"))
            else:
                self.state.update({k: v for k, v in event.items() if k != "state"})
                if event.get('frame_transport') == 'native_overlay' and event.get('state') in ('video', 'presented'):
                    self.last_frame = time.monotonic()

    def set_video_window(self, handle, width=None, height=None):
        self.video_window_handle = int(handle)
        if width and height:
            self.video_rectangle = (int(width), int(height))
        if self.media.state() == QProcess.ProcessState.Running and self.state.get('frame_transport') == 'native_overlay':
            self.media.write((json.dumps({'window': self.video_window_handle, 'width': self.video_rectangle[0],
                                         'height': self.video_rectangle[1]}) + '\n').encode())

    def _radio_output(self):
        data = bytes(self.radio.readAllStandardOutput())
        with (self.root / "logs" / "receiver-console.log").open("ab") as stream:
            stream.write(data)
        self.radio_buffer += data
        lines = self.radio_buffer.split(b"\n")
        self.radio_buffer = lines.pop()[-65536:]
        for line in lines:
            if not line.startswith(b"FITLAB_EVENT "):
                continue
            try:
                event = json.loads(line[13:])
            except (ValueError, UnicodeDecodeError):
                continue
            if event.get("state") == "error":
                self._error(event.get("error", "Ошибка приёмника"))
            elif event.get("notice"):
                notice = event['notice']
                if notice in ('RX1 подключён', 'RX2 подключён'):
                    if not self.receiver_notice_pending:
                        self.receiver_notice_pending = True
                        QTimer.singleShot(350, self._connected_receivers_notice)
                else:
                    self.message.emit(notice)
            elif event.get("warning"):
                self.message.emit(event["warning"] + " · приём продолжается на доступном RX")
            if event.get('selected_camera_profile'):
                self.cameraSelected.emit(event['selected_camera_profile'])
                if self.camera_search:
                    self.camera_search.active = event['selected_camera_profile']['identity']
            if not event.get('radio_tuning', {}).get('channel'):
                event.pop('radio_tuning', None)
            self.state.update({k: v for k, v in event.items() if k not in ("state", "rtp_packets")})
            for observation in event.get('observed_cameras', []):
                if self.camera_search:
                    self.camera_search.heard(observation['identity'], observation['last_seen'])
                self.seen_cameras[observation['identity']] = observation['last_seen']
            if event.get('camera_identity'):
                if self.camera_search:
                    self.camera_search.heard(event['camera_identity'], event['camera_identity_monotonic'])
                self.seen_cameras[event['camera_identity']] = event['camera_identity_monotonic']

    def _connected_receivers_notice(self):
        self.receiver_notice_pending = False
        if not self.running:
            return
        indexes = sorted(r['index'] + 1 for r in self.state.get('receivers', [])
                         if r.get('connection') in ('waiting', 'receiving') and r.get('process_id'))
        if indexes == [1, 2]:
            self.message.emit('Подключены RX1 и RX2')
        elif indexes:
            self.message.emit(f'RX{indexes[0]} подключён')

    def _search_camera(self, now):
        if not self.running or not self.camera_search or self.handover:
            return
        state = self.state
        # The remote receiver owns RF scanning. A missing LAN connection is
        # never a reason to retune or change the selected key on this master.
        if self.mode == 'lan' and not any(
                identity != self.camera_search.active and 0 <= now - stamp < 1.5
                for identity, stamp in self.seen_cameras.items()):
            return
        blocked = (self.selection_pinned or self.search_blocked or (self.root / 'config/pending-radio-switch.json').exists()
                   or (self.root / 'config/pending-pairing.json').exists()
                   or state.get('recording') in ('starting', 'recording', 'finishing')
                   or state.get('streaming') in ('starting', 'streaming'))
        action = self.camera_search.next(now, state['radio_tuning'],
            ready=any(r.get('connection') in ('waiting', 'receiving') and (r.get('process_id') or r.get('source') == 'lan')
                      for r in state.get('receivers', [])),
            active_video=bool(self.last_packet and now - self.last_packet < 2),
            active_control=state.get('control', {}).get('state') == 'connected', blocked=blocked)
        if not action or (self.mode == 'lan' and not action.get('identity')):
            return
        self._handover_camera(action)

    def select_camera(self, profile):
        if not self.running or self.handover or self.search_blocked:
            return False
        if self.state.get('recording') in ('starting', 'recording', 'finishing') or self.state.get('streaming') in ('starting', 'streaming'):
            return False
        tuning = profile['receiver_config']
        self.selection_pinned = True
        if self.camera_search and self.camera_search.active == profile['identity']:
            return True
        self._handover_camera(dict(identity=profile['identity'], channel=tuning['radio_channel'], width=tuning['radio_width']))
        return True

    def _handover_camera(self, action):
        now = time.monotonic()
        search, options = self.camera_search, dict(self.start_options)
        self.stop(_handover=True)
        operation = self.handover = object()
        deadline = now + 12
        self.state.update(phase='searching', camera_search='saved_channels')
        self.message.emit('Найдена знакомая камера · подключение' if action.get('identity') else 'Поиск камеры на сохранённых частотах')
        def resume():
            if self.handover is not operation:
                return  # The Stop button also cancels a pending automatic restart.
            if any(p.state() != QProcess.ProcessState.NotRunning for p in (self.radio, self.media)):
                if time.monotonic() < deadline:
                    QTimer.singleShot(100, resume)
                    return
                self.handover = None
                self._error('Не удалось освободить приёмники для поиска камеры')
                return
            try:
                if action.get('identity'):
                    from shared.pairing_store import PairingStore
                    profile = PairingStore(self.root).select_known(action['identity'], action if options['mode'] == 'local' and action.get('tuning_verified', True) else None)
                    if search:
                        search.active = profile['identity']
                    options['codec'] = profile['receiver_config'].get('codec', 'H.265').lower().replace('.', '')
                    self.cameraSelected.emit(profile)
                options.update(channel=action['channel'], width=action['width'])
                options['pin_selection'] = self.selection_pinned
                options['retune'] = options['mode'] == 'local'
                self.handover = None
                self.start(**options, _search=search)
            except (OSError, ValueError, KeyError) as exc:
                self.handover = None
                self._error(str(exc))
        QTimer.singleShot(100, resume)

    def _radio_finished(self, code, _):
        self._radio_output()
        if self.mode in ('local', 'lan') and self.running:
            self.stop()
            self.state["phase"] = "error" if code else "stopped"
            self.message.emit("Ошибка приёмника — откройте журнал" if code else "Сеанс приёма завершён")
            self.changed.emit(dict(self.state))

    def _media_finished(self, code, _):
        self._media_events()
        self._release_frame_memory()
        if self.running and code and self.video_window_handle and not self.native_video_failed:
            self.native_video_failed = True
            self.decoder_restart = True
            self.state.pop('frame_transport', None)
            self.message.emit('Переключение на совместимый видеовывод')
        if self.decoder_restart and self.running:
            self.decoder_restart = False
            self._launch_decoder()
            self.message.emit("Видеобуфер обновлён · приём RX продолжается")
            return
        if self.running:
            self.stop()
            self._error("Декодер завершился" + (f" · код {code}" if code else ""))

    def _decoder_error(self, error):
        if self.decoder_restart or not self.running:
            return
        if error == QProcess.ProcessError.Crashed and self.video_window_handle and not self.native_video_failed:
            return  # finished() restarts once with the compatible renderer.
        self._error(self.media.errorString())

    def _error(self, text):
        if self.running:
            self.stop()
        self.state.update(phase="error", error=text)
        self.message.emit(text)
        self.changed.emit(dict(self.state))

    def _optional_error(self, kind, process):
        self.state[kind] = "error"
        if kind == "recording":
            self.record_port = 0
            self.record_audio_port = 0
        else:
            self.stream_port = 0
        self.message.emit(("Ошибка записи: " if kind == "recording" else "Ошибка трансляции: ") + process.errorString())
        self.changed.emit(dict(self.state))

    def _tick(self):
        now = time.monotonic()
        self._search_camera(now)
        self.state["rtp_integrity"] = self.relay_integrity or self.rtp_stats.snapshot()
        self.state["mbps"] = (self.bytes - self.previous_bytes) * 8 / max(now - self.previous_time, .001) / 1e6
        self.state["rtp_fps"] = round(len(self.rtp_frame_timestamps) / max(now - self.previous_time, .001), 1)
        self.rtp_frame_timestamps.clear()
        self.previous_bytes, self.previous_time = self.bytes, now
        if self.running and self.state.get("phase") != "error":
            from master.media_recovery import decoder_stalled
            if decoder_stalled(now, self.last_packet, self.last_frame, self.last_decoder_restart):
                self.state['decoder_recovery_reason'] = 'frames_stalled'
                self.restart_decoder()
            if now - self.last_frame < .35:
                self.state["phase"] = "video"
            elif self.last_frame and now - self.last_frame < 2 and now - self.last_packet < 1:
                self.state["phase"] = "recovering"
            elif now - self.last_packet < 2:
                self.state["phase"] = "decoding"
            elif self.state.get("decoder"):
                self.state["phase"] = "waiting"
        self.state["frame_age"] = now - self.last_frame if self.last_frame else None
        self.state['available_cameras'] = [identity for identity, stamp in self.seen_cameras.items() if now - stamp < 4]
        if self.running and now - self.last_log >= 1:
            from shared.link_health import health_text
            from master.diagnostics import append_event
            health = self.health.add(self.state)
            self.state["health"] = health
            if now - self.last_health_log >= 10:
                append_event(self.root, {"time": time.time(), "operation": "link_health", **health})
                self.diagnostic.emit(health_text(health))
                self.last_health_log = now
            with (self.root / "telemetry" / "master-video.jsonl").open("a") as stream:
                stream.write(json.dumps({"time": time.time(), **self.state}, ensure_ascii=False) + "\n")
            self.last_log = now
            if self.record_port and self.record_path:
                try:
                    from shared.recording_storage import validate_recording_directory
                    validate_recording_directory(self.record_path.parent)
                    if shutil.disk_usage(self.record_path.parent).free < 100 * 1024**2:
                        self.message.emit("Запись остановлена: накопитель заполнен")
                        self.stop_recording()
                except (OSError, ValueError):
                    self.message.emit("Запись остановлена: накопитель отключён")
                    self.stop_recording()
        self.changed.emit(dict(self.state))
