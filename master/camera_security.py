"""Verified OpenIPC password rotation, durable credentials and remote rollback."""
import json
from pathlib import Path
import secrets
import shlex
import time

from master.camera import fingerprint
from master.camera_api import connect_camera, read_settings
from master.camera_credentials import CameraCredentialStore, security_receipt_path
from master.camera_radio import command
from master.camera_security_remote import BASE, BOOT, guardian, boot_script, apply_script, commit_script
from master.pairing import upload
from shared.pairing_store import atomic_write


def connect_verified_transport(host, username, password, root, transport='lan'):
    """Retry only a failed SSH handshake, never a password or identity rejection."""
    return connect_camera(host, username, password, root, transport)


def save_receipt(root, identity, value):
    path = security_receipt_path(root, identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(value, ensure_ascii=False).encode())


def check_identity(client, expected):
    if fingerprint(client.get_transport().get_remote_server_key()) != expected:
        raise ValueError('Подключена другая камера. Защита не изменена.')


def checked(client, text):
    code, value = command(client, text, timeout=12)
    if code:
        raise ValueError('Камера не подтвердила этап защиты')
    return value


def send_password(client, script, password):
    """No credential in argv, stdout, error text or the receipt."""
    stdin, stdout, stderr = client.exec_command(script, timeout=12)
    try:
        stdin.write(password + '\n')
        stdin.flush()
        stdin.channel.shutdown_write()
        deadline = time.monotonic() + 15
        channel = stdout.channel
        output = bytearray()
        while time.monotonic() < deadline:
            if channel.recv_ready():
                output.extend(channel.recv(1024))
            if channel.recv_stderr_ready():
                channel.recv_stderr(4096)  # Never expose remote diagnostics of a password command.
            if len(output) > 1024:
                break
            if channel.exit_status_ready() and not channel.recv_ready():
                if channel.recv_exit_status() == 0 and bytes(output).strip() == b'applied':
                    return
                break
            time.sleep(.01)
        raise ValueError('Смена пароля не подтверждена. Откат выполнится на камере.')
    finally:
        stdin.close(); stdout.close(); stderr.close(); stdout.channel.close()


def preflight(client):
    """A firmware must satisfy this adapter before any security write."""
    checked(client, '''[ "$(id -u)" = 0 ] && command -v majestic >/dev/null &&
command -v cli >/dev/null && test -f /etc/system.ok &&
test -f /etc/shadow && test ! -L /etc/shadow &&
test -x /usr/sbin/chpasswd && command -v flock >/dev/null && command -v nohup >/dev/null &&
test -d /etc/init.d && test ! -L /etc/fit-lab-security &&
{ test ! -e /etc/init.d/S01fitlab-security || grep -q 'FIT-LAB password rollback v1' /etc/init.d/S01fitlab-security; }''')
    help_text = command(client, '/usr/sbin/chpasswd --help 2>&1', timeout=5)[1]
    if 'sha256/512' not in help_text or 'Supplied passwords are in encrypted form' not in help_text:
        raise ValueError('Эта прошивка ещё не поддерживает проверенную смену пароля')


def recover(root, host, expected, receipt, vault):
    """Resolve a timed-out transaction without generating another password."""
    import paramiko
    for prefix in ('rotation-new:', 'rotation-old:'):
        credentials = vault._read(prefix + expected)
        if not credentials:
            continue
        try:
            client = connect_verified_transport(host, *credentials, root, 'lan')
        except paramiko.AuthenticationException:
            continue
        try:
            check_identity(client, expected)
            if prefix == 'rotation-new:':
                # Repair an older installed guard before reconciling a pending
                # transaction (BusyBox flock has no -w option).
                upload(client, BASE + '/guardian.sh', guardian().encode(), '700')
                read_settings(client, *credentials)
                old_credentials = vault._read('rotation-old:' + expected)
                if not old_credentials:
                    raise ValueError('Нет данных для проверки прежнего входа')
                try:
                    old = connect_verified_transport(host, *old_credentials, root, 'lan')
                except paramiko.AuthenticationException:
                    pass
                else:
                    old.close()
                    raise ValueError('Старый пароль ещё принимается')
                vault.durable_write('camera:' + expected, credentials)
                checked(client, commit_script(receipt['ticket']))
                receipt.update(stage='protected', verified_at=time.time(), old_password_rejected=True,
                               api_verified=True, password_storage=vault.storage_name)
            else:
                remote = checked(client, 'cat ' + shlex.quote(f"{BASE}/{receipt['ticket']}/state") + ' 2>/dev/null || echo missing')
                pending = checked(client, f'cat {BASE}/pending 2>/dev/null || true')
                if remote not in ('rolled_back', 'missing') or pending:
                    raise ValueError('Откат ещё не завершён. Повторите проверку через три минуты.')
                vault.durable_write('camera:' + expected, credentials)
                receipt.update(stage='rolled_back', verified_at=time.time())
            save_receipt(root, expected, receipt)
            return {'state': 'security_saved' if receipt['stage'] == 'protected' else 'security_rolled_back',
                    'security': receipt}
        finally:
            client.close()
    raise ValueError('Нужна проверка входа по LAN. Данные восстановления сохранены в Связке ключей.')


def protect_operation(host, username, password, root, expected_fingerprint,
                      transport='lan', operation_id=None, cancel=None):
    def cancelled():
        if cancel is not None and cancel.is_set():
            raise ValueError('Настройка защиты отменена')
    cancelled()
    if transport != 'lan':
        raise ValueError('Для защиты камеры подключите LAN')
    if username != 'root' or not expected_fingerprint.startswith('SHA256:'):
        raise ValueError('Нужен подтверждённый вход владельца камеры')
    import fcntl
    import paramiko
    root = Path(root)
    lock_path = root / 'config/camera-security.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Защита камеры уже настраивается') from None
        vault = CameraCredentialStore(root)
        path = security_receipt_path(root, expected_fingerprint)
        previous = json.loads(path.read_text()) if path.exists() else {}
        if previous.get('stage') == 'pending':
            return recover(root, host, expected_fingerprint, previous, vault)
        client = connect_verified_transport(host, username, password, root, 'lan')
        changed = False
        receipt = None
        phase = 'preflight'
        try:
            check_identity(client, expected_fingerprint)
            preflight(client)
            phase = 'verify_authentication_config'
            settings = read_settings(client, username, password)
            if settings.get('config', {}).get('system', {}).get('unsafe') is not False:
                raise ValueError('Прошивка не подтвердила обязательную авторизацию. Нужна проверка профиля защиты.')
            cancelled()
            # Repeat clicks verify an existing protected identity, not rotate again.
            if previous.get('stage') == 'protected' and vault._read('rotation-new:' + expected_fingerprint) == (username, password):
                read_settings(client, username, password)
                return {'state': 'security_saved', 'security': previous}
            new_password = secrets.token_urlsafe(24)
            phase = 'save_old_credential'
            vault.durable_write('rotation-old:' + expected_fingerprint, (username, password))
            phase = 'save_new_credential'
            vault.durable_write('rotation-new:' + expected_fingerprint, (username, new_password))
            receipt = dict(schema=1, adapter='openipc-busybox-v1', ticket=secrets.token_hex(16),
                           fingerprint=expected_fingerprint, host=host, stage='pending',
                           created_at=time.time(), operation_id=operation_id)
            # Durable new credentials precede every remote mutation.
            save_receipt(root, expected_fingerprint, receipt)
            phase = 'prepare_remote'
            checked(client, f'umask 077; mkdir -p {BASE} && chmod 700 {BASE}')
            upload(client, BASE + '/guardian.sh', guardian().encode(), '700')
            upload(client, BOOT, boot_script().encode(), '700')
            cancelled()
            changed = True
            phase = 'apply_password'
            send_password(client, apply_script(receipt['ticket']), new_password)
            # Keep the original SSH session for immediate rollback while a new
            # connection proves that the new password actually works.
            phase = 'verify_new_login'
            verified = connect_verified_transport(host, username, new_password, root, 'lan')
            try:
                check_identity(verified, expected_fingerprint)
                phase = 'verify_api'
                read_settings(verified, username, new_password)
                phase = 'reject_old_login'
                try:
                    old = connect_verified_transport(host, username, password, root, 'lan')
                except paramiko.AuthenticationException:
                    pass
                else:
                    old.close()
                    raise ValueError('Старый пароль ещё принимается')
                vault.durable_write('camera:' + expected_fingerprint, (username, new_password))
                cancelled()
                phase = 'commit'
                checked(verified, commit_script(receipt['ticket']))
            finally:
                verified.close()
            receipt.update(stage='protected', verified_at=time.time(), old_password_rejected=True,
                           api_verified=True, password_storage=vault.storage_name)
            save_receipt(root, expected_fingerprint, receipt)
            return {'state': 'security_saved', 'security': receipt}
        except Exception as exc:
            from master.diagnostics import append_event
            append_event(root, {'time': time.time(), 'operation': 'camera_security_failed',
                'phase': phase, 'failure_type': type(exc).__name__, 'password_change_started': changed})
            if changed:
                try:
                    checked(client, f"/bin/sh {BASE}/guardian.sh rollback 0 {receipt['ticket']}")
                except Exception:
                    pass  # Independent watchdog and boot rollback remain armed.
            if receipt:
                receipt.update(failed_phase=phase, failure_type=type(exc).__name__)
                save_receipt(root, expected_fingerprint, receipt)
            # Keep the pending vault entries; never hide an uncertain write.
            raise ValueError('Защита не завершена. Проверьте LAN и повторите «Защитить вход»: приложение проверит результат и восстановит доступ.') from None
        finally:
            client.close()
