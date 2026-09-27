"""LAN-only pairing, pinned camera identity, RF proof and durable rollback."""
import fcntl
import hashlib
import json
import sys
from pathlib import Path
import re
import shlex
import time

from master.camera_api import connect_camera
from master.camera_radio import command, inspect_radio
from master.pairing_remote import BASE, BOOT, KEY, RESTART, activation_script, boot_script
from shared.pairing_store import PairingStore, atomic_write


def checked(client, text, timeout=8):
    code, output = command(client, text, timeout=timeout)
    if code:
        raise ValueError('Камера отклонила этап привязки')
    return output


def upload(client, path, payload, mode='600'):
    # Binary key bytes are SSH channel input. Neither argv nor an error contains them.
    quoted = shlex.quote(path)
    stdin, stdout, stderr = client.exec_command(
        f'umask 077; cat > {quoted}.upload && chmod {mode} {quoted}.upload && mv {quoted}.upload {quoted}', timeout=8)
    try:
        stdin.write(payload)
        stdin.flush()
        stdin.channel.shutdown_write()
        stdout.read(1024)
        stderr.read(1024)
        if stdout.channel.recv_exit_status():
            raise ValueError('Не удалось передать файл привязки')
    finally:
        stdin.close(); stdout.close(); stderr.close()
    digest = checked(client, 'sha256sum ' + quoted).split()[0]
    if digest != hashlib.sha256(payload).hexdigest():
        raise ValueError('Проверка переданного файла не прошла')


def remote_status(client, op):
    return checked(client, 'cat ' + shlex.quote(op + '/status') + ' 2>/dev/null || echo missing')


def preserve_video_on_restart(client, radio, root, host):
    """Persist video and radio fields before a vendor restart can overwrite them."""
    vendor = radio.get('vendor_ini', {})
    if not radio.get('vendor_managed'):
        return radio, {}
    if not vendor:
        raise ValueError('Не удалось проверить сохранённые настройки камеры')
    from master.camera_vendor import update_script
    values = {key: checked(client, 'cli -g .video0.' + field) for key, field in
              (('fps', 'fps'), ('Size', 'size'), ('codec', 'codec'), ('bitrate', 'bitrate'))}
    radio_fields = {'channel': ('channel', '.wireless.channel'), 'txpower': ('power', '.wireless.txpower'),
                    'mcs_index': ('mcs', '.broadcast.mcs_index')}
    values.update({key: str(radio['config'][field]) for key, (field, _) in radio_fields.items()
                   if field in radio.get('config', {})})
    differences = {path: {key: {'before': data['values'].get(key), 'after': value}
                          for key, value in values.items() if data['values'].get(key) != value}
                   for path, data in vendor.items()}
    differences = {path: changes for path, changes in differences.items() if changes}
    if not differences:
        return radio, {}
    scripts = [update_script(path, vendor[path], {k: v['after'] for k, v in changes.items()})
               for path, changes in differences.items()]
    backup = root / 'config/camera-backups'
    backup.mkdir(exist_ok=True)
    atomic_write(backup / f'pairing-video-{time.time_ns()}.json',
                 json.dumps({'host': host, 'fields': differences}).encode())
    guards = ['exec 9>/tmp/fit-lab-radio.flock', 'flock -n 9 || exit 75']
    for key, field in (('fps', 'fps'), ('Size', 'size'), ('codec', 'codec'), ('bitrate', 'bitrate')):
        guards.append(f'[ "$(cli -g .video0.{field})" = {shlex.quote(values[key])} ] || exit 1')
    for key, (_, field) in radio_fields.items():
        if key in values:
            guards.append(f'[ "$(wifibroadcast cli -g {field})" = {shlex.quote(values[key])} ] || exit 1')
    for path, data in vendor.items():
        guards.append(f'[ "$(sha256sum {shlex.quote(path)} | cut -d " " -f 1)" = {shlex.quote(data["digest"])} ] || exit 1')
    guards.extend('sh -c ' + shlex.quote(script) + ' 9>&- || exit 1' for script in scripts)
    checked(client, 'sh -c ' + shlex.quote('\n'.join(guards)), timeout=12)
    refreshed = inspect_radio(client)
    if any(data['values'].get(key) != value for data in refreshed.get('vendor_ini', {}).values()
           for key, value in values.items()):
        raise ValueError('Сохранение текущего видеопрофиля не подтверждено')
    return refreshed, differences


def reconcile(client, store, receipt, cancel=True):
    if receipt.get('local_only'):
        active = store.read(store.active_path)
        committed = bool(active and active['ticket'] == receipt['ticket'] and active['stage'] == 'committed')
        store.finish(receipt, committed)
        return committed
    op = BASE + '/' + receipt['ticket']
    status = remote_status(client, op)
    from master.diagnostics import append_event
    check, _ = command(client, 'cmp -s ' + shlex.quote(op + '/previous.key') + ' ' + shlex.quote(KEY))
    append_event(store.root, {'time': time.time(), 'operation': 'pairing_recovery_status',
                             'state': status[:64], 'previous_key_matches': check == 0})
    if status == 'rollback_failed' and check == 0 and not receipt.get('service_recovery_attempted'):
        # The original key is already back; only the short service restart
        # failed. Never discard the pending receipt without camera readback.
        if not inspect_radio(client).get('restart_ready'):
            raise ValueError('Ключ восстановлен; радиослужба требует восстановления по LAN')
        receipt['service_recovery_attempted'] = True
        store.save(receipt)
        script = recovery_script(op)
        upload(client, op + '/recover-service.sh', script.encode(), '700')
        checked(client, 'nohup setsid sh ' + shlex.quote(op + '/recover-service.sh') + ' </dev/null >/dev/null 2>&1 &')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(.5)
            status = remote_status(client, op)
            if status == 'rolled_back':
                break
    if status in ('verifying', 'restarting', 'rolling_back') and cancel:
        checked(client, 'touch ' + shlex.quote(op + '/cancel'))
        deadline = time.monotonic() + 20
        while status in ('verifying', 'restarting', 'rolling_back') and time.monotonic() < deadline:
            time.sleep(.2)
            status = remote_status(client, op)
    if status == 'committed':
        store.finish(receipt, True)
        return True
    if status in ('rolled_back', 'cancelled', 'busy', 'invalid_key', 'backup_failed', 'video_conflict', 'conflict') or (status == 'missing' and receipt['stage'] == 'prepared'):
        store.finish(receipt, False)
        return False
    raise ValueError('Привязка не завершена · сохранён журнал восстановления, нужен LAN')


def recovery_script(op):
    if not re.fullmatch(re.escape(BASE) + r'/[0-9a-f]{32}', op):
        raise ValueError('Неверная операция восстановления')
    return f'''#!/bin/sh
umask 077
op={shlex.quote(op)}
exec 9>/tmp/fit-lab-radio.flock
flock -n 9 || exit 75
[ "$(cat "$op/status")" = rollback_failed ] || exit 1
[ -e /etc/system.ok ] || exit 1
cmp -s "$op/previous.key" {shlex.quote(KEY)} || exit 1
restart_radio() {{
{RESTART.replace('timeout 8 ', 'timeout 20 ')}
}}
echo recovering_service > "$op/status"
restart_radio || {{ echo rollback_failed > "$op/status"; exit 1; }}
pidof wfb_tx >/dev/null || {{ echo rollback_failed > "$op/status"; exit 1; }}
cmp -s "$op/previous.key" {shlex.quote(KEY)} || {{ echo rollback_failed > "$op/status"; exit 1; }}
echo rolled_back > "$op/status"
rm -f {shlex.quote(BASE + '/pending')}
sync
'''


def pair_operation(host, username, password, root, transport='lan', renew=False, operation_id=None):
    if transport != 'lan':
        raise ValueError('Привязка ключей выполняется только по LAN')
    root = Path(root)
    store = PairingStore(root)
    root.joinpath('config').mkdir(exist_ok=True)
    with (root / 'config/.pairing.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client = connect_camera(host, username, password, root, transport='lan')
        receipt = None
        phase = 'identity'
        try:
            server_key = client.get_transport().get_remote_server_key()
            mac = checked(client, 'cat /sys/class/net/eth0/address')
            if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac):
                raise ValueError('Не удалось определить аппаратную идентичность камеры')
            from master.camera import fingerprint
            identity = store.camera_identity(server_key.asbytes(), fingerprint(server_key), mac)
            pending = store.pending()
            if pending:
                if pending['identity'] != identity:
                    raise ValueError('Подключите прежнюю камеру для завершения незаконченной привязки')
                committed = reconcile(client, store, pending)
                return {'state': 'paired' if committed else 'pairing_rolled_back', 'pairing': pending}
            if sys.platform == 'darwin':
                from shared.usb_inventory import fast_devices
                if fast_devices() == []:
                    raise ValueError('Для проверки новой радиопривязки нужен RX на этом устройстве. Сейчас RX подключены к выносному приёмнику; ключи камеры не изменены.')
            phase = 'read_radio'
            radio = inspect_radio(client)
            if not radio.get('restart_ready') or radio.get('backend') != 'yaml':
                raise ValueError('Эта прошивка ещё не поддерживает безопасную привязку')
            # Known driver contract. Other camera families need a verified adapter.
            phase = 'preflight'
            checked(client, 'test -x /etc/init.d/S98wifibroadcast && test -x /usr/bin/wifibroadcast && test -f /etc/system.ok && test ! -L ' + KEY)
            codec = checked(client, 'cli -g .video0.codec')
            if codec not in ('h264', 'h265'):
                raise ValueError('Неизвестный видеокодек камеры')
            active = store.read(store.active_path)
            known = store.read(store.config / 'bindings' / (identity + '.json'))
            reuse = None
            if known and not renew and not known.get('revoked'):
                legacy_drone = store.folder(known['ticket']) / 'drone.key'
                if known.get('legacy_import') and not legacy_drone.exists():
                    # Preserve a previously working pair when migrating the old
                    # single-camera layout. Only the authenticated LAN channel
                    # and private vault see these bytes; nothing enters reports.
                    from nacl.public import PrivateKey
                    _, stream, errors = client.exec_command('cat ' + KEY, timeout=5)
                    try:
                        payload = stream.read(65)
                        if stream.channel.recv_exit_status() or len(payload) != 64:
                            raise ValueError('Не удалось проверить прежнюю привязку')
                        gs = store.key_for(known).read_bytes()
                        if bytes(PrivateKey(payload[:32]).public_key) != gs[32:] or payload[32:] != bytes(PrivateKey(gs[:32]).public_key):
                            raise ValueError('Ключ камеры изменён · выполните обновление привязки')
                        atomic_write(legacy_drone, payload)
                    finally:
                        stream.close(); errors.close()
                expected = hashlib.sha256((store.folder(known['ticket']) / 'drone.key').read_bytes()).hexdigest()
                camera_matches = checked(client, 'sha256sum ' + KEY).split()[0] == expected
                local_matches = store.active_key.is_file() and store.active_key.read_bytes() == (store.folder(known['ticket']) / 'gs.key').read_bytes()
                if camera_matches and local_matches and active and active['identity'] == identity:
                    return {'state': 'paired', 'pairing': known, 'unchanged': True,
                            'radio_settings': radio, 'codec': codec}
                if camera_matches:
                    reuse = known
            # Do not change keys while another receiver process owns the radio.
            with (root / 'logs/.fit-lab-radio-prepare.lock').open('a') as radio_lock:
                fcntl.flock(radio_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            phase = 'preserve_video'
            radio, video_sync = preserve_video_on_restart(client, radio, root, host) if not reuse else (radio, {})
            phase = 'prepare_keys'
            receipt = store.create(identity, host, fingerprint(server_key), reuse=reuse)
            receipt.update(ssh_key_type=server_key.get_name(), ssh_public_key=server_key.get_base64(),
                           ethernet_mac=mac,
                           camera_label=(known or {}).get('camera_label', 'OpenIPC · ' + mac[-8:]))
            receipt['video_persistence_updates'] = video_sync
            receipt['receiver_config'] = {'radio_channel': radio['live']['channel'],
                                          'radio_width': radio['live']['width'],
                                          'codec': 'H.265' if codec == 'h265' else 'H.264'}
            store.save(receipt)
            if reuse:
                receipt['local_only'] = True
                receipt['reused_binding'] = reuse['ticket']
                store.save(receipt)
                store.activate(receipt)
                from master.pairing_verify import verify_radio
                receipt['verification'] = verify_radio(root, receipt['ticket'], host, username, password, radio['live'], codec)
                if not receipt['verification']['passed']:
                    store.finish(receipt, False)
                    return {'state': 'pairing_rolled_back', 'error': 'Сохранённая привязка не прошла радиопроверку'}
                store.finish(receipt, True)
                return {'state': 'paired', 'pairing': receipt, 'radio_settings': radio, 'codec': codec, 'reused': True}
            op = BASE + '/' + receipt['ticket']
            checked(client, 'umask 077; mkdir -p ' + shlex.quote(op) + '; chmod 700 ' + BASE + ' ' + shlex.quote(op))
            # Refuse to overwrite an unrelated early-boot script.
            existing = checked(client, 'test ! -f ' + BOOT + ' || head -n 2 ' + BOOT)
            if existing and 'FIT-LAB pairing recovery' not in existing:
                raise ValueError('Имя службы восстановления уже занято на камере')
            upload(client, BOOT, boot_script().replace('#!/bin/sh', '#!/bin/sh\n# FIT-LAB pairing recovery', 1).encode(), '700')
            upload(client, op + '/new.key', (store.folder(receipt['ticket']) / 'drone.key').read_bytes())
            # Restarting vendor services must preserve current FPS/resolution.
            preflight = []
            for path, data in radio.get('vendor_ini', {}).items():
                preflight.append(f'[ "$(sha256sum {shlex.quote(path)} | cut -d " " -f 1)" = {shlex.quote(data["digest"])} ] || {{ echo conflict > "$op/status"; exit 1; }}')
                for key, field in (('fps','fps'), ('Size','size'), ('codec','codec'), ('bitrate','bitrate')):
                    if key in data.get('values', {}):
                        preflight.append(f'[ "$(cli -g .video0.{field})" = {shlex.quote(data["values"][key])} ] || {{ echo video_conflict > "$op/status"; exit 1; }}')
            upload(client, op + '/activate.sh', activation_script(receipt['ticket'], '\n'.join(preflight)).encode(), '700')
            receipt['stage'] = 'launching'
            store.save(receipt)
            checked(client, 'nohup setsid sh ' + shlex.quote(op + '/activate.sh') + ' </dev/null >/dev/null 2>&1 &')
            deadline = time.monotonic() + 20
            status = remote_status(client, op)
            while status in ('missing', 'restarting') and time.monotonic() < deadline:
                time.sleep(.2)
                status = remote_status(client, op)
            if status != 'verifying':
                raise ValueError('Камера не подтвердила запуск новой привязки: ' + status)
            store.activate(receipt)
            receipt['stage'] = 'verifying'
            store.save(receipt)
            from master.pairing_verify import verify_radio
            verification = verify_radio(root, receipt['ticket'], host, username, password, radio['live'], codec)
            receipt['verification'] = verification
            store.save(receipt)
            if not verification['passed']:
                raise ValueError('Радиопроверка новой привязки не пройдена')
            receipt['stage'] = 'committing'
            store.save(receipt)
            checked(client, 'test "$(cat ' + shlex.quote(op + '/status') + ')" = verifying && printf %s ' + receipt['ticket'] + ' > ' + shlex.quote(op + '/commit'))
            for _ in range(25):
                if remote_status(client, op) == 'committed':
                    store.finish(receipt, True)
                    result = {'state': 'paired', 'pairing': receipt, 'codec': codec}
                    try:
                        result['radio_settings'] = inspect_radio(client)
                    except Exception:
                        result['notice'] = 'Привязка сохранена · обновите параметры после восстановления связи'
                    return result
                time.sleep(.2)
            raise ValueError('Нет окончательного подтверждения камеры')
        except Exception as exc:
            from master.diagnostics import append_event
            append_event(root, {'time': time.time(), 'operation': 'pairing_failed',
                'phase': phase, 'failure_type': type(exc).__name__, 'keys_prepared': receipt is not None})
            if receipt and store.pending():
                receipt['failure_reason'] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                store.save(receipt)
                try:
                    committed = reconcile(client, store, receipt)
                    if committed:
                        return {'state': 'paired', 'pairing': receipt}
                    return {'state': 'pairing_rolled_back', 'pairing': receipt,
                            'error': 'Привязка отменена · прежние ключи восстановлены'}
                except Exception:
                    pass
            # No secret-dependent exceptions or subprocess stderr are exported.
            return {'state': 'error', 'error': str(exc) if isinstance(exc, (ValueError, BlockingIOError)) else
                    'Связь с камерой прервалась · подключите LAN для восстановления привязки'}
        finally:
            client.close()
