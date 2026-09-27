"""LAN camera discovery and authenticated OpenIPC profile onboarding.

An open port is a candidate, never proof of a supported model. Camera profiles
become bound only after verified SSH identity and an authenticated capability read.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import socket
import re
from copy import deepcopy
from pathlib import Path
from time import monotonic
from collections import defaultdict
from threading import RLock

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from shared.camera_profiles import load_profiles, resolve_profile
from master.camera_request import CameraRequest

_handshake_locks = defaultdict(RLock)
_recent_fingerprints = {}


def valid_host(value: str) -> str:
    value = value.strip()
    if value == "openipc.local":
        return value
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise ValueError('Укажите адрес камеры или нажмите «Найти» для поиска в сети') from None
    if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
        raise ValueError("Укажите локальный IPv4-адрес камеры")
    return str(address)


def fingerprint(key) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def discover(host: str, fallback=True, cancel=None) -> dict:
    host = valid_host(host)
    candidates = [host, "openipc.local"] if fallback and host != "openipc.local" else [host]
    for candidate in candidates:
        if cancel is not None and cancel.is_set():
            break
        try:
            address = socket.gethostbyname(candidate)
            valid_host(address)
            web_url = None
            openipc_web = False
            authentication_required = False
            connection = http.client.HTTPConnection(address, timeout=1)
            try:
                connection.request("GET", "/")
                response = connection.getresponse()
                authentication_required = response.status == 401
                if response.status in (200, 301, 302, 401, 403):
                    web_url = f"http://{address}/"
                    headers = ' '.join(str(v) for _, v in response.getheaders())
                    preview = response.read(8192).decode('utf-8', errors='replace')
                    openipc_web = bool(re.search(r'\b(?:openipc|majestic)\b', headers+' '+preview, re.I))
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()
            if cancel is not None and cancel.is_set():
                break
            response = ""
            try:
                with socket.create_connection((address, 554), timeout=1) as sock:
                    sock.settimeout(1)
                    sock.sendall(f"OPTIONS rtsp://{address}/stream=0 RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
                    response = sock.recv(4096).decode("ascii", errors="replace")
                    if response.startswith("RTSP/1.0") and "majestic" not in response.lower():
                        try:
                            sock.sendall(f"DESCRIBE rtsp://{address}/stream=0 RTSP/1.0\r\nCSeq: 2\r\nAccept: application/sdp\r\n\r\n".encode())
                            response += sock.recv(4096).decode("ascii", errors="replace")
                        except OSError:
                            pass
            except OSError:
                pass
            if response.startswith("RTSP/1.0"):
                return {"state": "found", "host": address,
                        "family": ("OpenIPC / Majestic" if "majestic" in response.lower() or openipc_web else
                                   "TP-Link · IP-камера" if "tp-link ip-camera" in response.lower() else "RTSP-камера"),
                        "identified": False, "web_url": web_url, "video_service_available": True}
            if web_url:
                # A failed encoder must not disable the controls needed to
                # recover it. HTTP reachability is only a candidate; SSH
                # identity verification is still required for every write.
                return {"state": "found", "host": address, "family": "OpenIPC · веб-панель" if openipc_web else "Сетевая камера",
                        "identified": False, "web_url": web_url, "video_service_available": False,
                        "authentication_required": authentication_required}
        except (OSError, ValueError):
            continue
    return {"state": "offline", "host": host}


def discover_candidate(host, fallback=True, fingerprint_only_if_video=False, cancel=None, known_identities=None):
    result = discover(host, fallback=fallback, cancel=cancel)
    if result.get('state') != 'found':
        if not known_identities:
            return result
        result = dict(state='found', host=host, family='Сетевое устройство', video_service_available=False)
    if cancel is not None and cancel.is_set():
        return {'state': 'offline', 'host': host}
    from master.camera_lan import openipc_candidate
    if fingerprint_only_if_video and not openipc_candidate(result) and not (known_identities and result.get('authentication_required')):
        return result  # Do not repeatedly negotiate SSH with routers/web appliances.
    import paramiko
    transport = None
    try:
        with _handshake_locks[result['host']]:
            recent = _recent_fingerprints.get(result['host'])
            if recent and monotonic() - recent[0] < 5:
                result['candidate_fingerprint'] = recent[1]
            else:
                sock = socket.create_connection((result['host'], 22), timeout=1)
                transport = paramiko.Transport(sock)
                transport.start_client(timeout=4)
                result['candidate_fingerprint'] = fingerprint(transport.get_remote_server_key())
                _recent_fingerprints[result['host']] = (monotonic(), result['candidate_fingerprint'])
                transport.close()
                transport = None
    except (OSError, paramiko.SSHException):
        pass
    finally:
        if transport:
            transport.close()
    saved = (known_identities or {}).get(result.get('candidate_fingerprint'))
    if saved:
        result['family'] = saved['family']
    return result


def read_profile(host: str, username: str, password: str, data_root: Path,
                 approved_fingerprint: str | None = None, transport='lan') -> dict:
    import paramiko
    host = valid_host(host)
    known_file = data_root / "config" / "camera_known_hosts"
    client = paramiko.SSHClient()
    if known_file.exists():
        client.load_host_keys(str(known_file))
    # A replacement at the same LAN address needs explicit confirmation of
    # its new fingerprint; never silently replace a pin from RF discovery.
    if approved_fingerprint and transport == 'lan' and host in client.get_host_keys():
        del client.get_host_keys()[host]

    class TrustNeeded(Exception):
        def __init__(self, fp):
            self.fp = fp

    class VerifyHost(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, ssh, hostname, key):
            fp = fingerprint(key)
            if approved_fingerprint != fp:
                raise TrustNeeded(fp)
            ssh.get_host_keys().add(hostname, key.get_name(), key)

    client.set_missing_host_key_policy(VerifyHost())
    if transport == 'radio':
        from master.camera_api import configure_radio_pin
        configure_radio_pin(client, host, data_root)
    relay = None
    try:
        from master.camera_api import control_socket
        relay = control_socket(transport)
        with _handshake_locks[host]:
            client.connect(host, username=username, password=password or None,
                           allow_agent=not bool(password), look_for_keys=False,
                           timeout=5, auth_timeout=10, banner_timeout=10, sock=relay)
            key = client.get_transport().get_remote_server_key()
            if transport == 'lan':
                _recent_fingerprints[host] = (monotonic(), fingerprint(key))
        # load_system_host_keys() is read-only in Paramiko: save_host_keys()
        # would otherwise write an empty app pin file for already-known hosts.
        client.get_host_keys().add(host, key.get_name(), key)
        # These are fixed read-only commands. Never read private keys or dump
        # the whole camera configuration into diagnostics.
        commands = {"hostname": "hostname", "platform": "uname -m",
                    "cli": "command -v cli", "majestic": "command -v majestic",
                    "ethernet_mac": "cat /sys/class/net/eth0/address",
                    "codec": "cli -g .video0.codec", "size": "cli -g .video0.size",
                    "fps": "cli -g .video0.fps", "bitrate": "cli -g .video0.bitrate",
                    "gop": "cli -g .video0.gopSize", "osd_enabled": "cli -g .osd.enabled",
                    "osd_template": "cli -g .osd.template", "msposd": "command -v msposd",
                    "radio_service": "command -v wifibroadcast",
                    "radio_tunnel": "command -v wfb_tun",
                    "adaptive_link": "command -v alink_drone",
                    "radio_driver": "readlink /sys/class/net/wlan0/device/driver",
                    "soc": "ipcinfo -c", "sensor": "ipcinfo -s",
                    "firmware": "awk -F= '$1 == \"VERSION_ID\" {gsub(/\"/, \"\", $2); print $2}' /etc/os-release"}
        values = {}
        from master.camera_radio import command_sections
        replies = command_sections(client, list(commands.values()))
        for name, (code, value) in zip(commands, replies):
            values[name] = value[:2048] if code == 0 else ''
        if not values["cli"] or not values["majestic"] or values["codec"] not in ("h264", "h265"):
            return {"state": "unsupported", "host": host,
                    "error": "Камера доступна, но профиль OpenIPC не подтверждён. Настройки не изменены."}
        fp = fingerprint(key)
        observed = {"family": "openipc", **{k: values[k] for k in ('soc', 'sensor', 'firmware') if values[k]}}
        if values['radio_driver']:
            observed['radio_driver'] = Path(values['radio_driver']).name
        compatibility = resolve_profile(load_profiles(data_root / "config" / "camera-profiles"),
                                        observed, ["video.parameters.read"])
        values["osd_engine"] = "MSP DisplayPort + Majestic" if values["msposd"] else "Majestic"
        profile = {"schema": 1, "state": "bound", "host": host, "username": username,
                   "fingerprint": fp, "family": compatibility["label"], "values": values,
                   "observed": observed,
                   "compatibility_profile": compatibility["id"], "driver": compatibility["driver"],
                   "capabilities": compatibility["capabilities"], "control_ready": False,
                   "identity": hashlib.sha256(key.asbytes() + (b"\0" + values["ethernet_mac"].encode() if re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", values["ethernet_mac"]) else b"")).hexdigest()[:24]}
        if re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', values['ethernet_mac']):
            from shared.pairing_store import PairingStore
            profile['identity'] = PairingStore(data_root).camera_identity(key.asbytes(), fp, values['ethernet_mac'])
        folder = data_root / "config" / "cameras"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{profile['identity']}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(target)
        client.save_host_keys(str(known_file))
        known_file.chmod(0o600)
        try:
            from master.camera_api import read_settings, save_public_settings
            profile["settings"] = read_settings(client, username, password)
            save_public_settings(data_root, profile["settings"])
            from master.camera_restore import CameraRestoreStore
            CameraRestoreStore(data_root, fp).initial(profile['settings'])
        except (OSError, ValueError, paramiko.SSHException):
            profile["settings_unavailable"] = True
        from master.camera_capabilities import assess
        from master.camera_radio import inspect_radio
        try:
            profile['radio_settings'] = inspect_radio(client)
        except (OSError, ValueError, paramiko.SSHException):
            profile['radio_settings'] = {}
        profile['assessment'] = assess(values, profile.get('radio_settings'), profile.get('settings'))
        profile['capabilities'] = resolve_profile(load_profiles(data_root / "config" / "camera-profiles"),
            observed, profile['assessment']['capabilities'])['capabilities']
        # Persist only the device passport, never raw configuration or credentials.
        public = {k: v for k, v in profile.items() if k not in ('settings', 'radio_settings')}
        temporary.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(target)
        return profile
    except TrustNeeded as exc:
        return {"state": "trust_required", "host": host, "fingerprint": exc.fp}
    except paramiko.BadHostKeyException as exc:
        if transport == 'lan':
            return {'state': 'trust_required', 'host': host, 'fingerprint': fingerprint(exc.key),
                    'identity_changed': True}
        return {"state": "error", "error": "Изменилась SSH-идентичность камеры. Привязка остановлена."}
    except paramiko.AuthenticationException:
        return {"state": "auth_required", "host": host, "error": "Нужны данные входа в камеру"}
    except (OSError, paramiko.SSHException) as exc:
        return {"state": "error", "host": host, "error": str(exc)}
    finally:
        client.close()
        if relay:
            relay.close()


class CameraJob(QThread):
    result = Signal(dict)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation())
        except Exception as exc:
            self.result.emit({"state": "error", "error": str(exc)})


class CameraManager(QObject):
    changed = Signal(dict)
    commandChanged = Signal(dict)
    lanDiscovered = Signal(dict)

    def __init__(self, data_root: Path, host="192.168.1.10", parent=None):
        super().__init__(parent)
        self.root, self._host = data_root, host
        self._transport, self._radio_connected = 'lan', False
        self.generation = 0
        self._lan_available = False
        self.job = None
        self.lan_job = None
        self.active_request = None
        self.pending_job = None
        self.closed = False
        self.last = None
        self.credentials = None
        self.credentials_store = None
        self.settings = None
        self.radio_settings = None
        self.coordinated_ticket = None
        self.bound_host = None
        self.timer = QTimer(self)
        self.timer.setInterval(10000)
        self.timer.timeout.connect(self.scan)
        self.timer.start()
        QTimer.singleShot(500, self.scan)

    @property
    def host(self):
        return self._host

    @host.setter
    def host(self, value):
        if value != self._host:
            self._host = value
            self.credentials = self.bound_host = self.settings = self.radio_settings = None
            self._lan_available = False
            self._invalidate('Камера изменена')

    @property
    def transport(self):
        return self._transport

    @transport.setter
    def transport(self, value):
        if value not in ('lan', 'radio'):
            raise ValueError('Неизвестный способ подключения')
        if value != self._transport:
            self._transport = value
            self._invalidate('Способ подключения изменён')

    @property
    def radio_connected(self):
        return self._radio_connected

    @radio_connected.setter
    def radio_connected(self, value):
        lost = self._radio_connected and not value
        self._radio_connected = bool(value)
        if lost and self.transport == 'radio' and not self.coordinated_ticket:
            # Echo is a link indicator, not the outcome of an authenticated
            # SSH transaction. Killing its local worker midway can discard the
            # prepare receipt or interrupt persistence/readback after a write.
            # Let the one in-flight request finish under its own timeout; never
            # preserve a queued mutation or replay the active request.
            self._cancel_pending('Нет ответа по радио')

    def _context(self):
        return self.host, self.transport, self.generation

    @property
    def busy(self):
        return bool((self.active_request and not self.active_request.terminal) or self.pending_job)

    @property
    def user_busy(self):
        """Background discovery must not disable a deliberate Connect action."""
        return bool(self.pending_job or (self.active_request and not self.active_request.terminal
                                        and (self.active_request.label or self.active_request.writing)))

    def _command(self, request, state, message):
        if request.terminal:
            return
        request.terminal = state not in ('queued', 'running')
        if not request.label:
            return
        event = {'operation_id': request.operation_id, 'command_state': state,
                 'label': request.label, 'message': message, 'writing': request.writing,
                 'host': request.context[0], 'transport': request.context[1]}
        now = monotonic()
        event['elapsed_ms'] = round((now - request.created_at) * 1000)
        event['queue_ms'] = round(((request.started_at or now) - request.created_at) * 1000)
        if request.started_at is not None:
            event['execution_ms'] = round((now - request.started_at) * 1000)
        from master.diagnostics import append_event
        import time
        append_event(self.root, {'time': time.time(), 'operation': 'camera_command', **event})
        self.commandChanged.emit(event)

    def _cancel_pending(self, reason):
        request, self.pending_job = self.pending_job, None
        if request:
            request.cancel.set()
            self._command(request, 'cancelled', reason + ' · запрос не отправлен')

    def _invalidate(self, reason):
        self.generation += 1
        self._cancel_pending(reason)
        request = self.active_request
        if request and not request.terminal:
            request.cancel.set()
            message = reason + (' · результат записи не подтверждён, обновите параметры'
                                if request.writing else ' · запрос отменён')
            self._command(request, 'unconfirmed' if request.writing else 'cancelled', message)

    def scan(self):
        if self.closed:
            return
        if self.transport == 'radio':
            self.changed.emit({'state': 'found' if self.radio_connected else 'offline', 'host': self.host,
                               'transport': 'radio', 'family': 'OpenIPC · радиоканал'})
            if self.lan_job is None and not self.busy:
                host = self.host
                self.lan_job = CameraJob(lambda: discover_candidate(host), self)
                self.lan_job.result.connect(self.lanDiscovered.emit)
                self.lan_job.finished.connect(self._lan_finished)
                self.lan_job.start()
            return
        host = self.host
        self._run(lambda request: discover_candidate(host, cancel=request.cancel))

    @Slot()
    def _lan_finished(self):
        job, self.lan_job = self.lan_job, None
        if job is not None:
            job.deleteLater()

    def bind(self, username, password, approved=None):
        host = self.host
        transport = self.transport
        return self._run(lambda _: self._authenticate(host, username, password, approved, transport),
                         user=True, label='Подключение камеры', credentials=(username, password))

    def _authenticate(self, host, username, password, approved, transport):
        result = read_profile(host, username, password, self.root, approved, transport)
        if result.get('state') == 'bound' and self.credentials_store is not None:
            try:
                self.credentials_store.remember(result['fingerprint'], (username, password))
                result['credential_storage'] = 'saved'
            except (OSError, ValueError):
                result['credential_storage'] = 'session_only'
        return result

    def bind_saved(self, identity=None, approved=None):
        host, transport = self.host, self.transport
        def authenticate(request):
            try:
                candidates = self.credentials_store.candidates(identity) if self.credentials_store else []
            except (OSError, ValueError):
                candidates = []
            if not candidates:
                return {'state': 'auth_required', 'host': host, 'reason': 'no_saved_credentials',
                        'error': 'Войдите в камеру в разделе «Камера»'}
            for credentials in candidates:
                request.credentials = credentials
                result = self._authenticate(host, *credentials, approved, transport)
                if result.get('state') != 'auth_required':
                    return result
            return result
        return self._run(authenticate, user=True, label='Подключение камеры')

    def protect(self, expected_fingerprint):
        if self.transport != 'lan' or not self.credentials or self.bound_host != self.host:
            self.changed.emit({'state': 'error', 'error': 'Подключите камеру по LAN и выполните вход'})
            return False
        from master.camera_security import protect_operation
        host, credentials = self.host, self.credentials
        # Keep Keychain operations in the signed Station process. A separate
        # Python worker has a different macOS identity and can prompt repeatedly.
        return self._run(lambda request: protect_operation(host, *credentials, self.root,
            expected_fingerprint=expected_fingerprint, transport='lan', cancel=request.cancel,
            operation_id=request.operation_id), user=True, writing=True, label='Защита входа')

    def refresh_settings(self, background=False):
        return self._settings_job(background=background)

    def pair_keys(self, renew=False):
        if self.transport != 'lan' or not self.credentials or self.bound_host != self.host:
            self.changed.emit({'state': 'auth_required', 'error': 'Подключите камеру по LAN и выполните вход'})
            return False
        from master.camera_worker import call
        host, credentials = self.host, self.credentials
        return self._run(lambda request: call('pair', host, *credentials, self.root,
                         transport='lan', renew=renew, cancel=request.cancel,
                         operation_id=request.operation_id), user=True, writing=True, label='Привязка радио')

    def apply_settings(self, changes):
        return self._settings_job(changes)

    def _settings_job(self, changes=None, background=False):
        if not self.credentials or self.bound_host != self.host:
            self.changed.emit({"state": "auth_required", "error": "Подключите камеру для настройки"})
            return False
        from master.camera_worker import call
        host, credentials = self.host, self.credentials
        baseline = deepcopy(self.settings.get("config", {}) if self.settings else {})
        changes = deepcopy(changes)
        transport = self.transport
        return self._run(lambda request: dict(call("settings", host, *credentials, self.root,
                         requested=changes, baseline=baseline, transport=transport,
                         cancel=request.cancel, operation_id=request.operation_id), background=background), user=not background,
                         label='' if background else 'Настройки камеры' if changes is not None else 'Чтение настроек',
                         writing=changes is not None)

    def read_radio(self, restart=False, channel=None, power=None, background=False):
        if not self.credentials or self.bound_host != self.host:
            self.changed.emit({"state": "auth_required", "error": "Подключите камеру для управления радиослужбой"})
            return False
        from master.camera_worker import call
        host, credentials, baseline = self.host, self.credentials, deepcopy(self.radio_settings)
        transport = self.transport
        return self._run(lambda request: dict(call("radio", host, *credentials, self.root,
                         restart=restart, channel=channel, baseline=baseline, power=power,
                         transport=transport, cancel=request.cancel, operation_id=request.operation_id), background=background),
                         user=not background, label='' if background else 'Радионастройки',
                         writing=restart or channel is not None or power is not None)

    def _run(self, operation, user=False, label='', writing=False, credentials=None):
        if self.closed:
            return False
        if user and self.transport == 'radio' and not self.radio_connected:
            self.changed.emit({'state': 'error', 'error': 'Нет ответа по радио · запрос не отправлен'})
            return False
        request = CameraRequest(self._context(), label, writing, credentials=credentials)
        request.operation = lambda: operation(request)
        if self.job is not None:
            # Read-only background synchronization must yield to an explicit
            # user command. Never interrupt a write or replay it automatically.
            if (user and self.active_request and not self.active_request.label
                    and not self.active_request.writing):
                self.active_request.cancel.set()
            # Repeated refresh clicks must not occupy the single SSH relay or
            # make a subsequent Apply wait for another identical snapshot.
            if not writing and label in ('Радионастройки', 'Чтение настроек'):
                for existing in (self.active_request, self.pending_job):
                    if (existing and not existing.terminal and not existing.writing
                            and existing.label == label and existing.context == request.context):
                        return True
            if writing and self.pending_job and not self.pending_job.writing and self.pending_job.label in ('Радионастройки', 'Чтение настроек'):
                self._cancel_pending('Приоритет отправки настроек')
            # A discovery poll must not silently swallow an Apply/Connect click.
            if user and self.pending_job is None:
                self.pending_job = request
                self._command(request, 'queued', 'Ожидает завершения текущей операции')
                return True
            if user:
                self.changed.emit({'state': 'error', 'error': 'Дождитесь завершения текущей операции'})
            return False
        return self._start_request(request)

    def switch_action(self, ticket, action, target=None):
        if not self.credentials or self.bound_host != self.host:
            return False
        from master.camera_worker import call
        host, credentials = self.host, self.credentials
        return self._run(lambda request: call('switch', host, *credentials, self.root,
                         ticket=ticket, action=action, target=target, transport='radio',
                         cancel=request.cancel, operation_id=request.operation_id),
                         user=True, label='Переключение радиоканала', writing=action != 'query')

    def _start_request(self, request):
        if not request.can_start(self._context()):
            self._command(request, 'cancelled', 'Запрос устарел · отправьте его заново')
            return False
        self.active_request = request
        request.started_at = monotonic()
        self.job = CameraJob(request.operation, self)
        self.job.result.connect(self._result)
        self.job.finished.connect(self._finished)
        if request.label:
            self._command(request, 'running', 'Отправка и проверка результата')
        self.job.start()
        return True

    @Slot()
    def _finished(self):
        job, self.job = self.job, None
        if job is not None:
            job.deleteLater()
        self.active_request = None
        request, self.pending_job = self.pending_job, None
        if request is not None and not self.closed:
            self._start_request(request)

    def _result(self, result):
        request = self.active_request
        if self.closed or request is None or request.cancel.is_set() or request.context != self._context():
            return  # Never apply a late result to another camera or connection.
        state = result.get('state')
        if state == 'radio_prepared':
            self.coordinated_ticket = result['switch']['ticket']
        if request.label:
            confirmed = state in ('bound', 'settings', 'settings_saved', 'radio_settings', 'radio_restarted',
                                  'radio_prepared', 'radio_armed', 'radio_pending', 'radio_switch_confirmed', 'radio_rolled_back', 'paired', 'security_saved', 'security_rolled_back')
            self._command(request, 'confirmed' if confirmed else 'unconfirmed' if request.writing else 'failed',
                          ('Подготовка подтверждена' if state in ('radio_prepared', 'radio_armed', 'radio_pending') else 'Подтверждено камерой')
                          if confirmed else result.get('error', 'Нужно подтверждение подключения'))
        else:
            request.terminal = True  # Background discovery has finished before UI observes it.
        if result.get('background') and state == 'error' and not request.writing:
            self.sync_retry_after = monotonic() + 20
            from master.diagnostics import append_event
            import time
            append_event(self.root, {'time': time.time(), 'operation': 'camera_background_read',
                                    'state': 'retry_later', 'transport': self.transport})
            return
        if state in ('error', 'auth_required', 'unsupported', 'radio_switch_failed'):
            self._cancel_pending('Предыдущая операция не подтверждена')
        # Repeated discovery should not overwrite authenticated profile fields.
        if result.get("state") == "found":
            self.host = result["host"]
            self._lan_available = True
            if result.get('candidate_fingerprint'):
                self.lanDiscovered.emit(result)
        elif state == 'offline' and self._lan_available:
            self._lan_available = False
            self._invalidate('Камера отключена от LAN')
        if result.get("state") == "bound":
            self.credentials = request.credentials
            self._lan_available = self.transport == 'lan'
            self.bound_host = result["host"]
            self.settings = result.get("settings")
            self.radio_settings = result.get('radio_settings')
        elif state in ('security_saved', 'security_rolled_back'):
            if self.credentials_store:
                identity = result['security']['fingerprint']
                self.credentials_store.cache.pop('camera:' + identity, None)
                try:
                    self.credentials = self.credentials_store.load(identity)
                except (OSError, ValueError):
                    self.credentials = None
                    result['credential_storage'] = 'unavailable'
        elif result.get("state") in ("settings", "settings_saved"):
            self.settings = result["settings"]
        elif result.get("state") in ("radio_settings", "radio_restarted", 'radio_switch_confirmed', 'radio_rolled_back', 'radio_switch_failed'):
            self.radio_settings = result["radio_settings"]
        self.last = result
        self.changed.emit(result)

    def close(self):
        self.closed = True
        self._invalidate('Приложение закрыто')
        self.timer.stop()
        if self.job:
            self.job.wait(45000)
        if self.lan_job:
            self.lan_job.wait(8000)
        self.credentials = self.settings = None
