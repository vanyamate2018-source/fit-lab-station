"""Two-phase RF changes with an on-camera rollback watchdog.

The first reply is only PREPARED. The camera cannot retune until the master
arms the receipt. A separate authenticated connection on the new channel must
confirm live values; otherwise the camera restores the old ones autonomously.
"""
import re
import shlex
import time
import uuid

from master.camera_radio import command, inspect_radio, launch_script, transaction_script


FAILURES = {
    'video_conflict': 'Режим видео отличается в памяти камеры и на SD. Сохраните видеорежим перед перезапуском.',
    'busy': 'Радиослужба занята другой операцией',
    'conflict': 'Настройки камеры изменились во время переключения',
    'save_failed': 'Камера не подтвердила сохранение настроек',
    'apply_failed': 'Драйвер не применил радионастройки',
    'stop_timeout': 'Предыдущая радиослужба не завершилась',
    'interrupted': 'Переключение на камере прервано',
    'rollback_conflict': 'Возврат отменён: настройки изменены извне',
    'rollback_failed': 'Камера не подтвердила возврат настроек',
}


def target_confirmed(snapshot, target):
    if not target or not snapshot.get('transmitter_running'):
        return False
    live, saved = snapshot.get('live', {}), snapshot.get('config', {})
    if any(live.get(key) != target.get(key) for key in ('channel', 'width', 'driver_dbm')):
        return False
    if any(saved.get(key) != target.get(key) for key in ('channel', 'width')):
        return False
    scale, power = snapshot.get('power_scale'), saved.get('power')
    if scale is None or power is None or power * scale != target.get('driver_dbm'):
        return False
    if snapshot.get('vendor_managed'):
        expected = {'channel': str(saved['channel']), 'txpower': str(power)}
        vendor = snapshot.get('vendor_ini', {})
        if not vendor or any(data['values'].get(k) != value for data in vendor.values()
                             for k, value in expected.items()):
            return False
    return True


def valid_ticket(ticket):
    if not isinstance(ticket, str) or not re.fullmatch(r'/tmp/fit-lab-radio-[a-f0-9]{32}', ticket):
        raise ValueError('Неизвестная операция переключения')
    return ticket


def coordinated_script(ticket, snapshot, changes, arm_seconds=20, confirm_seconds=40):
    valid_ticket(ticket)
    if snapshot.get('driver') != 'rtl88x2eu' or snapshot.get('power_scale') != .5:
        raise ValueError('Автовозврат этой радиоплаты ещё не проверен')
    if not snapshot.get('transmitter_running') or snapshot.get('adaptive'):
        raise ValueError('Для переключения нужен работающий передатчик без ALink')
    old = snapshot['config']
    if any(snapshot['live'].get(k) != old.get(k) for k in ('channel', 'width')):
        raise ValueError('Сначала восстановите соответствие сохранённой и рабочей частоты')
    backups, before, after, persisted = [], [], [], []
    if snapshot.get('vendor_managed') and changes:
        for index, path in enumerate(snapshot.get('vendor_ini', {})):
            backup = f'{ticket}.backup{index}'
            backups.append(backup)
            before.append(f'cp {shlex.quote(path)} {backup} && chmod 600 {backup} || exit 1')
            persisted.append(f'applied_hash_{index}=$(sha256sum {shlex.quote(path)} | cut -d " " -f 1)')
    cleanup = ' '.join([ticket + '.sh', ticket + '.arm', *backups])
    before += [f"trap 'rm -f {cleanup}' EXIT", f'echo prepared > {ticket}',
               'attempt=0', f'while [ ! -e {ticket}.arm ]; do',
               f'  [ "$attempt" -lt {arm_seconds * 10} ] || {{ echo expired > {ticket}; exit 0; }}',
               '  attempt=$((attempt + 1)); sleep 0.1', 'done',
               # Allow the arm reply to leave the old RF channel first.
               'sleep 3']
    after += [f'echo awaiting_ack > {ticket}', 'attempt=0',
              f'while [ ! -L {ticket}.decision ] && [ "$attempt" -lt {confirm_seconds * 10} ]; do',
              '  attempt=$((attempt + 1)); sleep 0.1', 'done',
              # A symlink is an atomic, mutually exclusive commit/rollback vote.
              f'ln -s rollback {ticket}.decision 2>/dev/null || :',
              f'if [ "$(readlink {ticket}.decision)" != commit ]; then']
    # Refuse to overwrite an external edit during the confirmation window.
    for key, value in changes.items():
        after.append(f'  [ "$(wifibroadcast cli -g .wireless.{key})" = {int(value)} ] || {{ echo rollback_conflict > {ticket}; exit 1; }}')
    for index, path in enumerate(snapshot.get('vendor_ini', {}) if changes else {}):
        after.append(f'  [ "$(sha256sum {shlex.quote(path)} | cut -d " " -f 1)" = "$applied_hash_{index}" ] || {{ echo rollback_conflict > {ticket}; exit 1; }}')
    for index, path in enumerate(snapshot.get('vendor_ini', {}) if changes else {}):
        after.append(f'  cat {ticket}.backup{index} > {shlex.quote(path)} || {{ echo rollback_failed > {ticket}; exit 1; }}')
    for key in changes:
        value = old['power' if key == 'txpower' else key]
        after.append(f'  wifibroadcast cli -s .wireless.{key} {int(value)} 9>&- || {{ echo rollback_failed > {ticket}; exit 1; }}')
    mode = 'HT40+' if old['width'] == 40 else 'HT20'
    after += [f'  iw dev wlan0 set channel {int(old["channel"])} {mode} 9>&- || {{ echo rollback_failed > {ticket}; exit 1; }}',
              f'  iw dev wlan0 set txpower fixed {int(old["power"]) * 50} 9>&- || {{ echo rollback_failed > {ticket}; exit 1; }}',
              f'  echo rolled_back > {ticket}', '  exit 0', 'fi']
    recovery = '\n'.join(after)
    # The channel may already have changed when the power ioctl fails. Run
    # the same guarded rollback immediately instead of exiting on the new RF.
    failed_apply = f'ln -s rollback {ticket}.decision 2>/dev/null || :\n' + recovery
    return transaction_script(ticket, snapshot.get('vendor_managed'), snapshot, changes,
                              '\n'.join(before), recovery, '\n'.join(persisted), failed_apply)[0]


def prepare_switch(client, snapshot, changes):
    ticket = '/tmp/fit-lab-radio-' + uuid.uuid4().hex
    script = coordinated_script(ticket, snapshot, changes)
    launch_script(client, ticket, script)
    for _ in range(30):
        _, stage = command(client, 'cat ' + ticket + ' 2>/dev/null')
        if stage == 'prepared':
            return {'ticket': ticket, 'old': snapshot['live'],
                    'target': {'channel': changes.get('channel', snapshot['live']['channel']),
                               'width': snapshot['live']['width'],
                               'driver_dbm': changes.get('txpower', snapshot['config']['power']) * .5},
                    'confirm_seconds': 40}
        if stage in ('busy', 'conflict'):
            raise ValueError('Камера занята или настройки изменились; переключение не началось')
        time.sleep(.1)
    raise ValueError('Камера не подтвердила подготовку; переключение не разрешено')


def switch_operation(host, username, password, root, ticket, action, target=None,
                     transport='radio', operation_id=None):
    from master.camera_api import connect_camera
    from master.diagnostics import append_event
    ticket = valid_ticket(ticket)
    if transport != 'radio' or action not in ('arm', 'commit', 'query'):
        raise ValueError('Переключение подтверждается только по радио')
    client = connect_camera(host, username, password, root, 'radio')
    audit = {'time': time.time(), 'operation': 'radio_switch_' + action,
             'transport': 'radio', 'operation_id': operation_id, 'ticket': ticket}
    try:
        _, stage = command(client, 'cat ' + ticket)
        if action == 'arm' and stage == 'prepared':
            code, _ = command(client, 'touch ' + ticket + '.arm')
            if code:
                raise ValueError('Переключение не подтверждено')
            audit['result'] = 'armed'
            return {'state': 'radio_armed', 'ticket': ticket}
        # A lost ARM reply must not launch the transaction again or leave the
        # master listening to the old channel until the watchdog rolls back.
        if action == 'arm' and stage in ('saving', 'applying', 'stopping', 'starting', 'awaiting_ack', 'done:0'):
            audit['result'] = 'already_armed'
            return {'state': 'radio_armed', 'ticket': ticket}
        if stage in FAILURES or (stage.startswith('done:') and stage != 'done:0'):
            snapshot = inspect_radio(client)
            audit.update(result=stage, live=snapshot.get('live'))
            return {'state': 'radio_switch_failed', 'ticket': ticket, 'stage': stage,
                    'error': FAILURES.get(stage, 'Радиослужба завершилась с ошибкой: ' + stage),
                    'radio_settings': snapshot}
        if stage not in ('awaiting_ack', 'done:0', 'rolled_back', 'expired'):
            audit['result'] = stage or 'receipt_unavailable'
            return {'state': 'radio_pending', 'ticket': ticket, 'stage': stage}
        snapshot = inspect_radio(client)
        if stage in ('rolled_back', 'expired'):
            audit['result'] = stage
            return {'state': 'radio_rolled_back', 'ticket': ticket, 'radio_settings': snapshot}
        if action == 'commit' and stage == 'awaiting_ack':
            if not target_confirmed(snapshot, target):
                raise ValueError('Новый канал или мощность не подтверждены драйвером')
            command(client, 'ln -s commit ' + ticket + '.decision 2>/dev/null || :')
            for _ in range(20):
                _, stage = command(client, 'cat ' + ticket)
                if stage in ('done:0', 'rolled_back'):
                    break
                time.sleep(.1)
            # A watchdog decision can win while SSH readback is in flight.
            # Report the values AFTER that decision, not the earlier snapshot.
            if stage in ('done:0', 'rolled_back'):
                snapshot = inspect_radio(client)
        audit.update(result=stage, live=snapshot['live'])
        if stage == 'done:0':
            if not target_confirmed(snapshot, target):
                return {'state': 'radio_switch_failed', 'ticket': ticket, 'stage': 'readback_mismatch',
                        'error': 'Переключение завершено, но текущие параметры не совпадают с запросом',
                        'radio_settings': snapshot}
            return {'state': 'radio_switch_confirmed', 'ticket': ticket, 'radio_settings': snapshot}
        if stage == 'rolled_back':
            return {'state': 'radio_rolled_back', 'ticket': ticket, 'radio_settings': snapshot}
        return {'state': 'radio_pending', 'ticket': ticket, 'stage': stage}
    except Exception as exc:
        audit.update(result='unconfirmed', error=type(exc).__name__)
        raise
    finally:
        append_event(root, audit)
        client.close()
