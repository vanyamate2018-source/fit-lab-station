"""Bounded WFB diagnostics and service control through the existing SSH identity.

No complete config, encryption keys, or credentials are exported. Service
discovery never sources a config file or runs a command supplied by that file.
"""
import json
import base64
import hashlib
import re
import shlex
import time
import uuid
from pathlib import Path

from shared.radio_settings import available_channels, channel_power_limits, diagnose, live_interface, power_value

RADIO_HARDWARE = '''for name in idVendor idProduct product manufacturer serial; do
  value=$(cat "/sys/class/net/wlan0/device/../$name" 2>/dev/null)
  [ -z "$value" ] || printf '%s=%s\\n' "$name" "$value"
done
printf 'mac=%s\\n' "$(cat /sys/class/net/wlan0/address 2>/dev/null)"
printf 'phy=%s\\n' "$(basename "$(readlink /sys/class/net/wlan0/phy80211)")"
'''


def command(client, text, timeout=5, limit=65536):
    deadline = time.monotonic() + timeout
    stdin, stdout, stderr = client.exec_command(text, timeout=timeout)
    try:
        channel = stdout.channel
        data = bytearray()
        error_size = 0
        # Drain both SSH windows. An unread stderr can block remote exit even
        # after stdout is complete; recv_exit_status has no timeout of its own.
        # One deadline also bounds a camera that keeps sending small fragments.
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Камера не завершила команду вовремя")
            received = False
            if channel.recv_ready():
                data.extend(channel.recv(min(16384, limit + 1 - len(data))))
                received = True
                if len(data) > limit:
                    raise ValueError("Ответ радиослужбы слишком большой")
            if channel.recv_stderr_ready():
                error_size += len(channel.recv_stderr(16384))
                received = True
                if error_size > limit:
                    raise ValueError("Слишком большой ответ диагностики камеры")
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                code = channel.recv_exit_status()
                break
            if not received:
                time.sleep(.01)
        # Only fixed, bounded diagnostics use this helper. Never echo stderr
        # containing an arbitrary service command or environment to the GUI.
        return code, data.decode("utf-8", errors="replace").strip()
    finally:
        stdin.close(); stdout.close(); stderr.close(); stdout.channel.close()


def command_sections(client, commands):
    """One SSH round trip for fixed read-only commands, retaining each status."""
    marker = 'FITLAB_SECTION_' + uuid.uuid4().hex
    parts = []
    for index, text in enumerate(commands):
        parts.append('(' + text + ')\nresult=$?\nprintf "\\n' + marker +
                     ':' + str(index) + ':%s\\n" "$result"')
    _, output = command(client, '\n'.join(parts), timeout=10, limit=131072)
    output = '\n' + output
    result, offset = [], 0
    for index in range(len(commands)):
        match = re.search(r'\n' + marker + ':' + str(index) + r':(\d+)(?:\n|$)', output[offset:])
        if match is None:
            raise ValueError('Неполный ответ диагностики радиолинии')
        result.append((int(match[1]), output[offset:offset + match.start()].strip()))
        offset += match.end()
    return result


# Export only capability markers, never the service source or private values.
SERVICE_CAPABILITIES = r'''service=$(command -v wifibroadcast)
case "$service" in /usr/bin/wifibroadcast|/usr/sbin/wifibroadcast|/sbin/wifibroadcast)
sh -n "$service" 2>/dev/null || exit 1
head -c 32768 "$service" | awk '
index($0,"/etc/wfb.yaml") {yaml=1}
index($0,"cli)") {cli=1}
index($0,"/etc/wfb.conf") {legacy=1}
index($0,"start_broadcast") {start=1}
/^[ \t]*start[ \t]*[|][ \t]*stop([ \t]*[|][ \t]*prepare)?[ \t]*[)]/ {restart=1}
index($0,"txpower * 50") {scale=1}
/^[[:space:]]*wifilink[[:space:]]+20[[:space:]]*&/ {vendor=1}
END {if(yaml)print "/etc/wfb.yaml"; if(cli)print "cli)";
if(legacy)print "/etc/wfb.conf"; if(start)print "start_broadcast";
if(restart)print "start|stop)"; if(scale)print "txpower * 50";
if(vendor)print "wifilink 20 &"}'
;; *) exit 1;; esac'''


def inspect_radio(client):
    sections = command_sections(client, [
        'cat /proc/uptime', SERVICE_CAPABILITIES,
        'readlink /sys/class/net/wlan0/device/driver', 'iw dev wlan0 info',
        "phy=$(basename \"$(readlink /sys/class/net/wlan0/phy80211)\"); case \"$phy\" in phy[0-9]*) iw phy \"$phy\" info | awk '/\\* [0-9]+ MHz \\[/ {print}' ;; *) exit 1;; esac",
        'pidof alink_drone >/dev/null', 'pidof wifilink',
        'pidof wfb_tx >/dev/null', 'test -e /etc/system.ok',
        RADIO_HARDWARE,
    ])
    (_, uptime), (_, source), (_, driver), (_, interface), (_, capabilities), \
        (code, _), (vendor_code, vendor_pids), (tx_code, _), (initialized, _), (_, hardware_text) = sections
    uptime = float(uptime.split()[0]) if re.fullmatch(r"[\d.]+ [\d.]+", uptime) else None
    backend = "yaml" if "/etc/wfb.yaml" in source and "cli)" in source else "legacy" if "/etc/wfb.conf" in source else "unknown"
    adaptive = code == 0
    config = {}
    if backend == "yaml":
        fields = (("channel", ".wireless.channel"), ("width", ".wireless.width"),
                  ("power", ".wireless.txpower"), ("mcs", ".broadcast.mcs_index"),
                  ("fec_k", ".broadcast.fec_k"), ("fec_n", ".broadcast.fec_n"))
        values = command_sections(client, ['wifibroadcast cli -g ' + path for _, path in fields])
        for (field, _), (status, value) in zip(fields, values):
            if status == 0 and re.fullmatch(r"-?\d{1,7}", value):
                config[field] = int(value)
    elif backend == "legacy":
        _, values = command(client, "awk -F= '/^(channel|bandwidth|txpower|driver_txpower_override|mcs_index|fec_k|fec_n)=/ {print}' /etc/wfb.conf")
        names = {"channel": "channel", "bandwidth": "width", "txpower": "power", "driver_txpower_override": "power_index", "mcs_index": "mcs", "fec_k": "fec_k", "fec_n": "fec_n"}
        for line in values.splitlines():
            key, _, value = line.partition("=")
            if key in names and re.fullmatch(r"-?\d{1,7}", value.strip()):
                config[names[key]] = int(value.strip())
    live = live_interface(interface)
    # `start` in this driver stops and relaunches the WFB processes. Refuse
    # first-boot initialization: it also rewrites unrelated video settings.
    restart_ready = backend == "yaml" and "start_broadcast" in source and "start|stop)" in source and initialized == 0
    driver_name = Path(driver).name if driver else ""
    scale = .5 if driver_name == "rtl88x2eu" and "txpower * 50" in source else None
    notices = diagnose(config, live, adaptive, backend)
    vendor_managed = bool(re.search(r"^\s*wifilink\s+20\s*&", source, re.M))
    vendor_ini = {}
    if vendor_managed:
        from master.camera_vendor import read_ini
        vendor_ini = read_ini(client)
        if vendor_code == 0 and len(vendor_pids.split()) > 1:
            notices.append("Несколько процессов RunCam · требуется перезапуск радиослужбы")
    if scale and "power" in config and "driver_dbm" in live and abs(config["power"] * scale - live["driver_dbm"]) > .1:
        notices.append("Сохранённая мощность ещё не применена")
    from shared.radio_settings import same_band_channels, working_band
    reported_channels = available_channels(capabilities)
    channels = same_band_channels(reported_channels, live)
    hardware = dict(line.split('=', 1) for line in hardware_text.splitlines()
                    if '=' in line and line.split('=', 1)[0] in ('idVendor', 'idProduct', 'product', 'manufacturer', 'serial', 'mac', 'phy'))
    hardware = {key: value[:120] for key, value in hardware.items()}
    import hashlib
    hardware_id = hashlib.sha256(json.dumps({**{k: v for k, v in hardware.items() if k != 'phy'},
                                            'driver': driver_name}, sort_keys=True).encode()).hexdigest()[:24] if hardware else None
    band = working_band(live.get('frequency_mhz'))
    if band:
        notices.append('Рабочий диапазон ' + ('2,4' if band == '2.4' else '5') + ' ГГц')
    else:
        notices.append('Рабочий диапазон не подтверждён · смена частоты недоступна')
    return {"backend": backend, "driver": driver_name, "config": config, "uptime_seconds": uptime,
            "live": live, "channels": channels, "reported_channels": reported_channels,
            "working_band": band, "hardware": hardware, "hardware_id": hardware_id, "adaptive": adaptive,
            "vendor_wifilink": vendor_code == 0,
            "vendor_managed": vendor_managed, "vendor_ini": vendor_ini,
            "vendor_instances": len(vendor_pids.split()) if vendor_code == 0 else 0,
            "power_scale": scale, "power_step": 1 if driver_name == 'rtl88x2eu' else .5,
            "power_limits": channel_power_limits(capabilities),
            "transmitter_running": tx_code == 0, "restart_ready": restart_ready,
            "notices": notices}


def transaction_script(ticket, vendor_managed, snapshot=None, changes=None, before_apply='', after_apply='',
                       after_persist='', on_apply_failure=''):
    """One camera-side lock covers validation, persistence and live application."""
    changes = changes or {}
    snapshot = snapshot or {}
    script_path = ticket + '.sh'
    lines = ['umask 077', 'exec 9>/tmp/fit-lab-radio.flock',
             f'if ! flock -n 9; then echo busy > {ticket}; exit 75; fi',
             f"trap 'rm -f {script_path}' EXIT",
             f"trap 'echo interrupted > {ticket}; exit 1' HUP INT TERM",
             f'echo validating > {ticket}']
    if before_apply:
        lines.append(before_apply)
    # Check after the optional arm wait, immediately before writes. External
    # tools do not necessarily honour our lock during that wait.
    for key, value in snapshot.get('config', {}).items():
        field = {'channel': '.wireless.channel', 'width': '.wireless.width',
                 'power': '.wireless.txpower', 'mcs': '.broadcast.mcs_index',
                 'fec_k': '.broadcast.fec_k', 'fec_n': '.broadcast.fec_n'}.get(key)
        if field:
            lines.append(f'[ "$(wifibroadcast cli -g {field})" = {int(value)} ] || {{ echo conflict > {ticket}; exit 1; }}')
    if vendor_managed and not changes:
        # Starting wifilink reloads video settings from BOTH vendor files.
        # Refuse before stopping anything if that would silently replace the
        # current video mode (e.g. SD card still says 30 FPS, Majestic says 60).
        for path, data in snapshot.get('vendor_ini', {}).items():
            lines.append(f'[ "$(sha256sum {shlex.quote(path)} | cut -d " " -f 1)" = {shlex.quote(data["digest"])} ] || {{ echo conflict > {ticket}; exit 1; }}')
            for key, setting in (('fps', 'fps'), ('codec', 'codec'), ('bitrate', 'bitrate'), ('Size', 'size')):
                if key in data.get('values', {}):
                    value = shlex.quote(data['values'][key])
                    lines.append(f'[ "$(cli -g .video0.{setting})" = {value} ] || {{ echo video_conflict > {ticket}; exit 1; }}')
    if changes:
        from master.camera_vendor import update_script
        vendor = snapshot.get('vendor_ini', {}) if vendor_managed else {}
        if vendor_managed and not vendor:
            raise ValueError('Файл настроек RunCam не найден')
        scripts = [update_script(path, data, {k: str(v) for k, v in changes.items()})
                   for path, data in vendor.items()]
        # Check ALL source files before changing the first one.
        for path, data in vendor.items():
            lines.append(f'[ "$(sha256sum {shlex.quote(path)} | cut -d " " -f 1)" = {shlex.quote(data["digest"])} ] || {{ echo conflict > {ticket}; exit 1; }}')
        lines.append(f'echo saving > {ticket}')
        for script in scripts:
            lines.append('sh -c ' + shlex.quote(script) + f' 9>&- || {{ echo save_failed > {ticket}; exit 1; }}')
        for key, value in changes.items():
            if key not in ('channel', 'txpower') or type(value) is not int:
                raise ValueError('Неверная радионастройка')
            lines.append(f'wifibroadcast cli -s .wireless.{key} {value} 9>&- || {{ echo save_failed > {ticket}; exit 1; }}')
    if after_persist:
        lines.append(after_persist)
    live_apply = bool(changes and snapshot.get('transmitter_running')
                      and snapshot.get('driver') == 'rtl88x2eu' and snapshot.get('power_scale') == .5)
    if live_apply:
        lines.append(f'echo applying > {ticket}')
        failure = f'echo apply_failed > {ticket}; ' + (on_apply_failure + '; ' if on_apply_failure else '') + 'exit 1'
        if 'channel' in changes:
            mode = 'HT40+' if snapshot['config']['width'] == 40 else 'HT20'
            lines.append(f'iw dev wlan0 set channel {changes["channel"]} {mode} 9>&- || {{ {failure}; }}')
        if 'txpower' in changes:
            lines.append(f'iw dev wlan0 set txpower fixed {changes["txpower"] * 50} 9>&- || {{ {failure}; }}')
    else:
        names = 'wfb_rx wfb_tx wfb_tun msposd mavfwd' + (' wifilink' if vendor_managed else '')
        lines += [f'echo stopping > {ticket}',
                  # Kill only positively identified processes, never a group or
                  # a shell matched by its arguments. The vendor stop sequence
                  # intermittently terminated the old restart controller.
                  f'for name in {names}; do',
                  '  for pid in $(pidof "$name"); do',
                  '    [ "$(cat /proc/$pid/comm 2>/dev/null)" = "$name" ] && kill -TERM "$pid" 2>/dev/null',
                  '  done', 'done', 'attempt=0',
                  f'while pidof {names} >/dev/null; do',
                  '  attempt=$((attempt + 1))',
                  f'  if [ "$attempt" -ge 30 ]; then echo stop_timeout > {ticket}; exit 1; fi',
                  '  sleep 0.1', 'done', f'echo starting > {ticket}',
                  # New services must NOT inherit our lock, or it would stay
                  # held for their entire lifetime. Isolate their process group.
                  'setsid timeout 8 wifibroadcast start </dev/null >/dev/null 2>&1 9>&-',
                  'result=$?', f'[ "$result" = 0 ] || {{ echo done:$result > {ticket}; exit "$result"; }}']
    if after_apply:
        lines.append(after_apply)
    lines.append(f'echo done:0 > {ticket}')
    return '\n'.join(lines) + '\n', live_apply


def restart_service(client, vendor_managed, snapshot=None, changes=None):
    """Launch once; poll a unique receipt if the initiating SSH channel closes."""
    ticket = '/tmp/fit-lab-radio-' + uuid.uuid4().hex
    script_path = ticket + '.sh'
    script, _ = transaction_script(ticket, vendor_managed, snapshot, changes)
    launch_script(client, ticket, script)
    return ticket


def launch_script(client, ticket, script):
    script_path = ticket + '.sh'
    # Separate session, and a script FILE rather than shell command text. Some
    # embedded process-name matchers inspect argv, including literal service
    # names in `sh -c ...`; the restart controller must not match its own kill.
    # SFTP negotiation failed on this camera. Stage the quoted script through
    # the already verified SSH exec channel.
    # Keep command text small and do not expose service names in SSH argv:
    # vendor supervisors may match their own names inside a staging command.
    upload = script_path + '.upload'
    code, _ = command(client, 'umask 077; : > ' + upload)
    if code:
        raise ValueError('Не удалось подготовить файл на камере')
    encoded = base64.b64encode(script.encode()).decode('ascii')
    for offset in range(0, len(encoded), 1536):
        code, _ = command(client, 'printf %s ' + shlex.quote(encoded[offset:offset+1536])
                          + ' | base64 -d >> ' + upload)
        if code:
            raise ValueError('Камера не подтвердила загрузку сценария')
    digest = hashlib.sha256(script.encode()).hexdigest()
    code, _ = command(client, '[ "$(sha256sum ' + upload + ' | cut -d " " -f 1)" = '
                      + digest + ' ] && chmod 700 ' + upload + ' && mv ' + upload + ' ' + script_path)
    if code:
        raise ValueError('Проверка сценария на камере не пройдена')
    # One launch only. If its reply is lost, polling this unique ticket resolves
    # ambiguity; never issue a second restart automatically.
    try:
        command(client, 'nohup setsid sh ' + shlex.quote(script_path) + ' </dev/null >/dev/null 2>&1 &', timeout=5)
    except (OSError, EOFError):
        pass
    except Exception as exc:
        import paramiko
        if not isinstance(exc, paramiko.SSHException):
            raise


def radio_operation(host, username, password, root, restart=False, channel=None, baseline=None, power=None, transport='lan', operation_id=None):
    from master.camera_api import connect_camera
    client = connect_camera(host, username, password, root, transport, reuse=True)
    history = []
    started = time.monotonic()
    audit = {"time": time.time(), "transport": transport, "operation_id": operation_id,
             "operation": "radio_apply" if restart or channel is not None or power is not None else "radio_read",
             "requested": {"channel": channel, "power_dbm": power}}
    def record(stage, snapshot, **extra):
        history.append({"stage": stage, "at": time.time(), **snapshot, **extra})
        target = root / "logs" / "camera-radio-operation.json"
        target.write_text(json.dumps({"host": host, "observations": history}, ensure_ascii=False, indent=2) + "\n")
    try:
        if transport == 'lan' and not (restart or channel is not None or power is not None):
            public_checks = {}
            for name, diagnostic_command in (("http_port", "cli -g .system.webPort"), ("listeners", "netstat -lntp"), ("init_services", "ls /etc/init.d"), ("firmware", "cat /etc/os-release"), ("soc", "ipcinfo -c"), ("sensor", "ipcinfo -s"),
                    ('radio_syntax', 'sh -n /usr/bin/wifibroadcast'),
                    ('pairing_preflight', 'test -e /etc/system.ok; echo initialized:$?; for f in /etc/drone.key /etc/gs.key; do printf "%s bytes:" "$f"; if test -f "$f"; then wc -c < "$f"; else echo absent; fi; done; for p in wfb_tx wfb_rx wfb_tun; do pidof "$p" >/dev/null; echo "$p running:$?"; done')):
                code, value = command(client, diagnostic_command)
                public_checks[name] = {"exit": code, "value": value[:8192]}
            (root / "logs/camera-services-public.json").write_text(json.dumps(public_checks, ensure_ascii=False, indent=2) + "\n")
            vendor_scripts = {}
            for path in ("/etc/runcam_cfg.sh", "/etc/user_config.sh", "/etc/init.d/S95majestic", "/etc/init.d/S70vendor"):
                code, source = command(client, "head -c 32768 " + path)
                if code == 0 and source.startswith("#!"):
                    vendor_scripts[path] = "\n".join(line for line in source.splitlines() if not re.search(r"key|password|secret|token", line, re.I))
            (root / "logs/camera-vendor-scripts-public.json").write_text(json.dumps(vendor_scripts, ensure_ascii=False, indent=2) + "\n")
            vendor_ini = {}
            for path in ("/etc/user.ini", "/mnt/mmcblk0p1/user.ini"):
                code, source = command(client, "awk -F= 'tolower($1) ~ /^[[:space:]]*(channel|txpower|driver_txpower_override|bandwidth|width|bitrate|fps|framerate|codec|resolution|resolutionratio|mcs_index|fec_k|fec_n|saturation|contrast|hue|luminance|flip|mirror|rotate|exposure|profile)[[:space:]]*$/ {print}' " + path)
                vendor_ini[path] = {"exit": code, "values": source}
            (root / "logs/camera-vendor-values-public.json").write_text(json.dumps(vendor_ini, ensure_ascii=False, indent=2) + "\n")
            # Read-only firmware code inspection, excluding every key/credential
            # line. Configuration files and process command lines are never dumped.
            _, service = command(client, "command -v wifibroadcast")
            if service in ("/usr/bin/wifibroadcast", "/usr/sbin/wifibroadcast", "/sbin/wifibroadcast"):
                _, source = command(client, "head -c 32768 " + service)
                public_source = "\n".join(line for line in source.splitlines() if not re.search(r"key|password|secret|token", line, re.I))
                (root / "logs/camera-radio-service-public.txt").write_text(public_source + "\n")
            _, link_service = command(client, "command -v wifilink")
            if link_service in ("/usr/bin/wifilink", "/usr/sbin/wifilink", "/sbin/wifilink"):
                _, source = command(client, "head -c 32768 " + link_service)
                if source.startswith("#!"):
                    source = "\n".join(line for line in source.splitlines() if not re.search(r"key|password|secret|token", line, re.I))
                    (root / "logs/camera-wifilink-public.txt").write_text(source + "\n")
                else:
                    _, hints = command(client, "strings " + link_service + " | awk '/wfb.yaml|user.ini|txpower|wifibroadcast|channel|Usage/ {print}'")
                    (root / "logs/camera-wifilink-public.txt").write_text(hints + "\n")
        result = inspect_radio(client)
        from shared.pairing_store import PairingStore
        pending_pairing = PairingStore(root).pending()
        if pending_pairing and pending_pairing.get('host') == host:
            ticket = pending_pairing.get('ticket', '')
            if re.fullmatch(r'[0-9a-f]{32}', ticket):
                status_code, status_text = command(client, 'cat /etc/fit-lab-pairing/' + ticket + '/status')
                result['pending_pairing'] = {'status': status_text[:64], 'exit': status_code}
        audit["before"] = {"saved": result["config"], "live": result["live"]}
        record("before", result)
        patch = {}
        if channel is not None or power is not None:
            target_channel = channel if channel is not None else result["config"].get("channel")
            if type(target_channel) is not int or target_channel not in result["channels"] or not result["restart_ready"]:
                raise ValueError("Камера не подтвердила этот канал")
            if result["adaptive"]:
                raise ValueError("Радионастройками управляет ALink. Ручная смена канала недоступна.")
            if not baseline or result["config"] != baseline.get("config"):
                raise ValueError("Радионастройки изменились. Обновите их перед записью.")
            if baseline.get('hardware_id') != result.get('hardware_id'):
                raise ValueError('Передатчик изменился. Обновите его параметры перед записью.')
            if result["config"].get("width") not in (20, 40):
                raise ValueError("Полоса камеры не поддерживается приёмником")
            patch = {}
            if channel is not None:
                patch["channel"] = channel
            if power is not None:
                patch["txpower"] = power_value(power, result, target_channel)
            backup = root / "config/camera-backups"
            backup.mkdir(exist_ok=True, parents=True)
            path = backup / f"radio-{time.time_ns()}.json"
            with path.open("x") as stream:
                path.chmod(0o600)
                json.dump({"host": host, "backend": result["backend"], "restore": {"channel": result["config"].get("channel"), "txpower": result["config"].get("power")},
                           "vendor_restore": {p: {k: data["values"].get(k) for k in patch} for p, data in result.get("vendor_ini", {}).items()}}, stream)
            restart = True
        if restart:
            if not result["restart_ready"]:
                raise ValueError("Команда перезапуска этой прошивки не подтверждена")
            if transport == 'radio':
                from master.radio_switch import prepare_switch
                prepared = prepare_switch(client, result, patch)
                audit['result'] = 'prepared_not_applied'
                audit['restart_ticket'] = prepared['ticket']
                return {'state': 'radio_prepared', 'host': host, 'switch': prepared}
            ticket = restart_service(client, result.get('vendor_managed'), result, patch)
            audit['apply_mode'] = 'live' if transaction_script(ticket, result.get('vendor_managed'), result, patch)[1] else 'restart'
            audit['restart_ticket'] = ticket
            # The camera supervises WFB too. Wait for its children to start,
            # then judge their real state; shell status alone is insufficient.
            import paramiko
            completed = False
            for attempt in range(40):
                time.sleep(.25)
                try:
                    _, stage = command(client, 'cat ' + ticket + ' 2>/dev/null')
                    audit['restart_stage'] = stage
                    failures = {'busy': 'Радиослужба занята другой операцией; настройки не изменены',
                                'video_conflict': 'Режим видео отличается в памяти камеры и на SD. Сохраните видеорежим перед перезапуском.',
                                'stop_timeout': 'Предыдущая радиослужба не завершилась',
                                'conflict': 'Настройки камеры изменились. Обновите их перед записью.',
                                'save_failed': 'Не подтверждено сохранение радионастроек',
                                'apply_failed': 'Драйвер не применил радионастройки',
                                'interrupted': 'Операция на камере прервана'}
                    if stage in failures:
                        raise ValueError(failures[stage])
                    if not stage.startswith('done:'):
                        continue
                    if stage != 'done:0':
                        raise ValueError('Радиослужба завершилась с ошибкой: ' + stage)
                    result = inspect_radio(client)
                except (OSError, EOFError, paramiko.SSHException):
                    client.close()
                    try:
                        client = connect_camera(host, username, password, root, transport)
                    except (OSError, EOFError, paramiko.SSHException):
                        pass
                    continue
                record("restarted", result, service_exit=stage, attempt=attempt)
                if result["transmitter_running"]:
                    completed = True
                    break
            if not completed:
                raise ValueError('Завершение перезапуска не подтверждено. Обновите радионастройки; повторная команда не отправлялась.')
            if not result["transmitter_running"]:
                raise ValueError("Радиослужба не подтвердила запуск. Обновите состояние камеры.")
            if not result["live"] or any(result["config"].get(k) != result["live"].get(k) for k in ("channel", "width")):
                raise ValueError("Радиослужба запущена, но канал не совпадает с сохранённым")
            if channel is not None and result["live"].get("channel") != channel:
                raise ValueError(f"Камера вернулась на канал {result['live'].get('channel')}; запрошенный канал {channel} не применён")
            if power is not None and abs(result["live"].get("driver_dbm", -999) - power) > .1:
                raise ValueError("Мощность сохранена, но драйвер не подтвердил её применение")
            if result.get("vendor_managed"):
                if result["vendor_instances"] != 1:
                    raise ValueError("Не подтверждён единственный процесс управления RunCam")
                expected = {"channel": str(result["config"].get("channel")), "txpower": str(result["config"].get("power"))}
                if not result["vendor_ini"] or any(data["values"].get(k) != value for data in result["vendor_ini"].values() for k, value in expected.items()):
                    raise ValueError("Настройки RunCam и радиодрайвера не совпадают")
        result["checked_at"] = time.time()
        target = root / "logs" / "camera-radio-status.json"
        target.write_text(json.dumps({"host": host, **result}, ensure_ascii=False, indent=2) + "\n")
        audit["result"] = "readback_confirmed"
        return {"state": "radio_restarted" if restart else "radio_settings", "host": host, "radio_settings": result}
    except Exception as exc:
        try:
            record("failed", inspect_radio(client))
        except Exception:
            pass
        audit.update(result="unconfirmed", error=str(exc))
        raise
    finally:
        if history:
            audit["after"] = {"saved": history[-1]["config"], "live": history[-1]["live"], "transmitter_running": history[-1]["transmitter_running"]}
        audit["duration_ms"] = round((time.monotonic() - started) * 1000)
        from master.diagnostics import append_event
        append_event(root, audit)
        client.close()
