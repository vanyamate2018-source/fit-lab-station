"""Majestic API over an authenticated, host-key-pinned SSH connection."""
import base64
import http.client
import json
import re
import shlex
import time
from pathlib import Path

from shared.camera_settings import apply_checked, fields, make_patch, needs_reload


class MajesticAPI:
    def __init__(self, client, username, password, legacy=False, timeout=5):
        self.client = client
        self.timeout = timeout
        self.authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        self.legacy = legacy
        self.last_response = self.last_write_response = self.last_write_error = None

    def __call__(self, method, path, payload=None):
        if path not in ("/api/v1/config.schema.json", "/api/v1/config.json", "/api/v1/config"):
            raise ValueError("Неподдерживаемая операция камеры")
        if method == "POST" and self.legacy:
            from urllib.parse import urlencode
            from shared.camera_settings import GROUPS, wire_values
            from master.camera_radio import command
            def leaves(node, prefix=""):
                for key, value in node.items():
                    dotted = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, dict):
                        yield from leaves(value, dotted)
                    else:
                        yield dotted, value
            # Only the validated patch reaches here; readback and partial
            # rollback remain the same for legacy and modern transports.
            for key, value in leaves(payload):
                if key.split('.')[0] not in GROUPS or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){1,5}", key):
                    raise ValueError("Недопустимый путь настройки")
                # The 2025 RunCam API changes runtime values only. Persist the
                # same validated leaf through its installed CLI before applying
                # it live; a later HUP readback also checks persistence.
                encoded = str(wire_values(value))
                status, _ = command(self.client, "cli -s " + shlex.quote('.' + key) + " " + shlex.quote(encoded))
                if status:
                    raise ValueError("Камера не подтвердила сохранение настройки")
                status, saved = command(self.client, "cli -g " + shlex.quote('.' + key))
                if status or saved != encoded.strip():
                    raise ValueError("Сохранённое значение не совпадает с запрошенным")
                self._request("GET", "/api/v1/set?" + urlencode({key: wire_values(value)}), writing=True)
            return {}
        return self._request(method, path, payload, writing=method == "POST")

    def _request(self, method, path, payload=None, writing=False):
        connection = http.client.HTTPConnection("127.0.0.1", timeout=self.timeout)
        try:
            connection.sock = self.client.get_transport().open_channel(
                "direct-tcpip", ("127.0.0.1", 80), ("127.0.0.1", 0), timeout=self.timeout)
            connection.sock.settimeout(self.timeout)
            from shared.camera_settings import wire_values
            body = json.dumps(wire_values(payload), ensure_ascii=False).encode() if payload is not None else None
            if body and len(body) > 1024 * 1024:
                raise ValueError("Слишком много настроек в одной операции")
            connection.request(method, path, body, {"Authorization": self.authorization,
                               "Content-Type": "application/json", "Connection": "close"})
            response = connection.getresponse()
            # Never store a write URL query: it can contain an OSD string.
            self.last_response = {"method": method, "path": path.split("?")[0], "status": response.status}
            if writing:
                self.last_write_response = self.last_response
            raw = b"" if writing and response.status == 202 and response.length is None else response.read(1024 * 1024 + 1)
            if response.status not in (200, 202, 204):
                raise ValueError(f"API камеры: HTTP {response.status}")
            if len(raw) > 1024 * 1024:
                raise ValueError("Ответ камеры слишком большой")
            if writing:
                if raw.strip().startswith(b"{"):
                    reply = json.loads(raw)
                    self.last_write_response["fields"] = list(reply) if isinstance(reply, dict) else []
                    if isinstance(reply, dict) and (reply.get("error") or reply.get("ok") is False):
                        raise ValueError("Камера отклонила настройку")
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Неверный формат настроек камеры")
            return data
        except OSError as exc:
            if writing:
                self.last_write_error = type(exc).__name__ + ": " + str(exc)
            raise
        except http.client.HTTPException as exc:
            if writing:
                self.last_write_error = type(exc).__name__ + ": " + str(exc)
            raise OSError("Соединение с API камеры прервано") from exc
        finally:
            connection.close()


def read_settings(client, username, password):
    api = MajesticAPI(client, username, password)
    schema = api("GET", "/api/v1/config.schema.json")
    config = api("GET", "/api/v1/config.json")
    if not fields(schema, config):
        raise ValueError("Прошивка не сообщила доступные параметры")
    return {"schema": schema, "config": config}


def save_public_settings(root, settings):
    # Only controls accepted by our credential filter, never the full config.
    public = fields(settings["schema"], settings["config"])
    (root / "logs/camera-settings-public.json").write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n")


def control_socket(transport):
    if transport == 'lan':
        return None
    if transport != 'radio':
        raise ValueError('Неизвестный канал управления')
    import socket
    return socket.create_connection(('127.0.0.1', 19022), timeout=5)


def connect_camera(host, username, password, root, transport='lan', reuse=False):
    if reuse and transport == 'radio':
        from master.camera_session import acquire, identity
        return acquire(identity(root, host, username, password),
                       lambda: connect_camera(host, username, password, root, transport))
    import paramiko
    import socket
    # Retry only establishment: no application command has been sent yet.
    for attempt in range(3):
        try:
            return _connect_camera_once(host, username, password, root, transport)
        except (paramiko.SSHException, OSError, EOFError) as exc:
            transient = (type(exc) is paramiko.SSHException and (
                str(exc) == 'No existing session' or str(exc).startswith('Error reading SSH protocol banner')))
            transient = transient or (transport == 'radio' and isinstance(
                exc, (socket.timeout, ConnectionResetError, ConnectionAbortedError, EOFError)))
            if not transient or attempt == 2:
                raise
            time.sleep(.5 * (attempt + 1))


def _connect_camera_once(host, username, password, root, transport='lan'):
    import paramiko
    from master.camera import valid_host
    client = paramiko.SSHClient()
    # Only FIT-LAB's explicitly pinned identity; no new-host auto-accept policy.
    client.load_host_keys(str(root / "config/camera_known_hosts"))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    if transport == 'radio':
        configure_radio_pin(client, host, root)
    relay = None
    try:
        relay = control_socket(transport)
        client.connect(valid_host(host), username=username, password=password or None,
                       allow_agent=not bool(password), look_for_keys=False,
                       timeout=12 if transport == 'radio' else 5, auth_timeout=10, banner_timeout=12 if transport == 'radio' else 10, sock=relay)
    except Exception:
        client.close()
        if relay:
            relay.close()
        raise
    return client


def configure_radio_pin(client, host, root):
    """Trust the selected camera's enrolled fingerprint, not the last LAN IP pin."""
    import paramiko
    from shared.pairing_store import PairingStore
    active = PairingStore(root).read(PairingStore(root).active_path)
    if not active:
        return
    expected = active.get('ssh_fingerprint')
    if not expected:
        raise ValueError('У профиля камеры нет сохранённой SSH-идентичности')
    if host in client.get_host_keys():
        del client.get_host_keys()[host]
    class SavedCameraPin(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, ssh, hostname, key):
            from master.camera import fingerprint
            if fingerprint(key) != expected:
                raise paramiko.SSHException('По радио ответила другая камера')
            ssh.get_host_keys().add(hostname, key.get_name(), key)
    client.set_missing_host_key_policy(SavedCameraPin())


def video_service_ready(client):
    from master.camera_radio import command
    code, listeners = command(client, "netstat -lnt")
    return code == 0 and any(re.search(r":554\s", line) and "LISTEN" in line for line in listeners.splitlines())


def guard_video_service(client, api, schema, baseline, changes, was_ready):
    """A saved API value is not proof that the camera's video SDK started."""
    if not was_ready or not changes:
        return
    from master.camera_radio import command
    from shared.camera_settings import get_value
    for attempt in range(8):
        if video_service_ready(client):
            return
        time.sleep(.5)
    current = api("GET", "/api/v1/config.json")
    # Do not overwrite a concurrent edit, even when recovering video.
    if any(get_value(current, key) != value for key, value in changes.items()):
        raise ValueError("Видеослужба не запустилась; настройки изменены извне. Обновите состояние камеры.")
    restore = {key: get_value(baseline, key) for key in changes}
    apply_checked(api, schema, current, restore, lambda _: None)
    code, _ = command(client, "test -x /etc/init.d/S95majestic")
    if code:
        raise ValueError("Настройки восстановлены; требуется перезапуск видеослужбы камеры")
    code, _ = command(client, "/etc/init.d/S95majestic restart >/dev/null 2>&1", timeout=15)
    for attempt in range(10):
        if video_service_ready(client):
            raise ValueError("Этот режим остановил видео. Предыдущие настройки и видеопоток восстановлены.")
        time.sleep(.5)
    raise ValueError("Настройки восстановлены, но камера ещё не подтвердила запуск видео")


def settings_operation(host, username, password, root: Path, requested=None, baseline=None, transport='lan', operation_id=None):
    client = connect_camera(host, username, password, root, transport, reuse=True)
    started = time.monotonic()
    changes = {}
    audit = {"time": time.time(), "transport": transport, "operation_id": operation_id,
             "operation": "camera_apply" if requested is not None else "camera_read"}
    try:
        from master.camera_radio import command
        import re
        _, firmware = command(client, "cat /etc/os-release")
        stamp = re.search(r"^TIME_STAMP=(\d+)$", firmware, re.M)
        legacy = bool(stamp and int(stamp[1]) < 1767225600)
        api = MajesticAPI(client, username, password, legacy=legacy, timeout=12 if transport == "radio" else 5)
        audit["protocol"] = "legacy_cli_and_set" if legacy else "nested_post"
        schema = api("GET", "/api/v1/config.schema.json")
        from master.camera import fingerprint
        from master.camera_restore import CameraRestoreStore
        restore_store = CameraRestoreStore(root, fingerprint(client.get_transport().get_remote_server_key()))
        if requested is None:
            config = api("GET", "/api/v1/config.json")
            restore_store.initial({'schema': schema, 'config': config})
        else:
            restore_store.initial({'schema': schema, 'config': baseline})
            changes = make_patch(schema, baseline, requested)
            was_ready = video_service_ready(client) if changes else False
            from shared.camera_settings import get_value
            audit["changes"] = {key: {"before": get_value(baseline, key), "requested": value} for key, value in changes.items()}
            def backup(values):
                folder = root / "config/camera-backups"
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"settings-{time.time_ns()}.json"
                with target.open("x", encoding="utf-8") as stream:
                    target.chmod(0o600)
                    json.dump({"host": host, "restore": values}, stream, ensure_ascii=False, indent=2)
            try:
                config = apply_checked(api, schema, baseline, requested, backup)
            except (ValueError, OSError) as exc:
                from master.camera_radio import command
                disk = {}
                for key in changes:
                    code, value = command(client, "cli -g ." + key)
                    disk[key] = {"exit": code, "value": value[:2048]}
                target = root / "logs/camera-settings-operation.json"
                audit["file_values"] = disk
                audit["transport_error"] = repr(exc.__cause__) if exc.__cause__ is not None else None
                target.write_text(json.dumps({"changed_paths": list(changes), "api_response": api.last_write_response, "file_values": disk}, ensure_ascii=False, indent=2) + "\n")
                raise
            if needs_reload(schema, baseline, changes):
                from master.camera_radio import command
                status, _ = command(client, "killall -HUP majestic")
                if status:
                    raise ValueError("Настройки сохранены, но видеослужба не подтвердила применение")
                # Reload is in-process. Its HTTP socket may briefly stop serving.
                time.sleep(1)
                for attempt in range(8):
                    try:
                        config = api("GET", "/api/v1/config.json")
                        from shared.camera_settings import get_value
                        if any(get_value(config, key) != value for key, value in changes.items()):
                            raise ValueError("После применения камера изменила значения. Обновите настройки.")
                        break
                    except OSError:
                        if attempt == 7:
                            raise ValueError("Настройки сохранены. Камера ещё не подтвердила применение — обновите состояние.")
                        time.sleep(1)
            guard_video_service(client, api, schema, baseline, changes, was_ready)
            # RunCam reloads its INI files at boot. Keep advertised video and
            # image leaves in that source of truth, too; never copy the whole
            # config or unknown fields off the camera.
            from master.camera_vendor import SETTING_KEYS, read_ini, write_ini
            from shared.camera_settings import wire_values
            vendor_changes = {SETTING_KEYS[key]: str(wire_values(value)) for key, value in changes.items() if key in SETTING_KEYS}
            if legacy and vendor_changes:
                vendor_code, vendor_tool = command(client, "command -v wifilink")
                if vendor_code == 0 and vendor_tool in ("/usr/bin/wifilink", "/usr/sbin/wifilink"):
                    before_ini = read_ini(client)
                    backup_folder = root / "config/camera-backups"
                    target = backup_folder / f"vendor-{time.time_ns()}.json"
                    with target.open("x") as stream:
                        target.chmod(0o600)
                        json.dump({"host": host, "restore": {p: {k: d["values"].get(k) for k in vendor_changes} for p, d in before_ini.items()}}, stream)
                    try:
                        write_ini(client, before_ini, vendor_changes)
                    except (OSError, ValueError) as exc:
                        audit["vendor_error"] = type(exc).__name__ + ": " + str(exc)
                        raise ValueError("Параметры видео применены, но сохранение RunCam для следующего запуска не подтверждено. Обновите настройки.") from exc
                    audit["vendor_persistence"] = "confirmed"
            restore_store.confirmed(schema, baseline, config, changes)
        save_public_settings(root, {"schema": schema, "config": config})
        audit["result"] = "readback_confirmed"
        audit["readback"] = {key: get_value(config, key) for key in changes}
        audit["available_fields"] = len(fields(schema, config))
        return {"state": "settings_saved" if requested is not None else "settings",
                "host": host, "settings": {"schema": schema, "config": config}}
    except Exception as exc:
        audit.update(result="unconfirmed", error=str(exc))
        raise
    finally:
        audit.update(duration_ms=round((time.monotonic() - started) * 1000), api_response=getattr(locals().get("api"), "last_write_response", None),
                     write_error=getattr(locals().get("api"), "last_write_error", None))
        from master.diagnostics import append_event
        append_event(root, audit)
        client.close()
