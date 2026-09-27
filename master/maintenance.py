"""Bounded camera checks under the Station application's Keychain identity."""
import json
import os
from pathlib import Path
import time


def camera_security_job():
    from master.camera import valid_host, read_profile
    from master.camera_credentials import CameraCredentialStore
    from master.camera_security import protect_operation
    from shared.pairing_store import PairingStore, atomic_write
    root = Path(os.environ['FIT_LAB_DATA_ROOT'])
    target = root / 'logs/camera-security-check.json'
    result = {'time': time.time(), 'state': 'error'}
    try:
        host = valid_host(os.environ.get('FIT_LAB_CAMERA_HOST', ''))
        identity = os.environ.get('FIT_LAB_CAMERA_ID', '')
        binding = next((p for p in PairingStore(root).profiles() if p['identity'] == identity), None)
        if not binding:
            raise ValueError('Нужна сохранённая камера')
        expected = binding['ssh_fingerprint']
        vault = CameraCredentialStore(root)
        credentials = vault.load(expected)
        if not credentials:
            raise ValueError('Нет сохранённого входа')
        if os.environ.get('FIT_LAB_RADIO_CHECK') == '1':
            from master.camera_api import connect_camera
            from master.camera_radio import command, inspect_radio
            transport = os.environ.get('FIT_LAB_CHECK_TRANSPORT', 'lan')
            if transport not in ('lan', 'radio'):
                raise ValueError('Неизвестный путь проверки')
            result.update(stage='ssh_connect', transport=transport)
            client = connect_camera(host, *credentials, root, transport=transport)
            try:
                result['stage'] = 'radio_read'
                radio = inspect_radio(client)
                _, temperature = command(client, 'cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null')
                result.update(state='radio_readback', live=radio.get('live'),
                              config=radio.get('config'), notices=radio.get('notices'),
                              temperature=temperature[:32])
            finally:
                client.close()
            atomic_write(root / 'logs/camera-radio-readback.json', json.dumps(result).encode())
            return 0
        if os.environ.get('FIT_LAB_AUDIO_CHECK') == '1':
            import subprocess
            import sys
            from master.camera_api import settings_operation, connect_camera
            from master.camera_radio import command
            from master.media_env import media_environment
            from shared.camera_settings import get_value
            client = connect_camera(host, *credentials, root)
            try:
                code, _ = command(client, 'pidof majestic')
                if code:
                    result['video_service_was_stopped'] = True
                    status, _ = command(client, '/etc/init.d/S95majestic start >/dev/null 2>&1', timeout=15)
                    result['video_restart_exit'] = status
                    time.sleep(3)
                _, version = command(client, 'majestic -v 2>&1', timeout=5)
                result['majestic_version'] = version[:250]
            finally:
                client.close()
            before = settings_operation(host, *credentials, root)
            baseline = before['settings']['config']
            changed = settings_operation(host, *credentials, root,
                requested={'audio.enabled': True}, baseline=baseline)
            config = changed['settings']['config']
            result.update(state='microphone_enabled', audio_enabled=get_value(config, 'audio.enabled'),
                          codec=get_value(config, 'audio.codec'), sample_rate=get_value(config, 'audio.srate'))
            atomic_write(root / 'logs/camera-audio-check.json', json.dumps(result).encode())
            payload = json.dumps(dict(host=host, username=credentials[0], password=credentials[1], seconds=25))
            child = subprocess.run([sys.executable, '-m', 'master.audio_check'], input=payload,
                capture_output=True, text=True, env=media_environment(root), timeout=40)
            result['playback'] = json.loads(child.stdout) if child.returncode == 0 else {'state': 'worker_failed'}
            atomic_write(root / 'logs/camera-audio-check.json', json.dumps(result).encode())
            return 0 if result['playback']['state'] == 'played' else 1
        if os.environ.get('FIT_LAB_PAIR_RENEW') == '1':
            from master.camera_worker import call
            paired = call('pair', host, *credentials, root, transport='lan', renew=True)
            receipt = paired.get('pairing', {})
            result.update(state=paired.get('state', 'error'), error=paired.get('error'),
                          identity=receipt.get('identity'), ticket=receipt.get('ticket'),
                          verification=receipt.get('verification'), receiver_config=receipt.get('receiver_config'))
            atomic_write(target, json.dumps(result, ensure_ascii=False).encode())
            return 0 if result['state'] == 'paired' else 1
        if os.environ.get('FIT_LAB_INSPECT_NETWORK') == '1':
            from master.camera_api import connect_camera
            from master.camera_radio import command
            client = connect_camera(host, *credentials, root, transport='radio')
            try:
                code, addresses = command(client, 'ip -4 addr show dev eth0; ip -4 route show')
                result.update(state='network_verified', ethernet=addresses[:4096], exit_code=code)
            finally:
                client.close()
            atomic_write(target, json.dumps(result, ensure_ascii=False).encode())
            return 0
        if os.environ.get('FIT_LAB_SECURITY_APPLY') == '1':
            # Protection requires a previously pinned host and checks the
            # enrolled fingerprint itself, including during recovery.
            result.update(protect_operation(host, *credentials, root, expected))
        else:
            for attempt in range(3):
                profile = read_profile(host, *credentials, root, approved_fingerprint=expected)
                if profile.get('state') != 'error' or attempt == 2:
                    break
                if not any(message in profile.get('error', '') for message in ('No existing session', 'SSH protocol banner')):
                    break
                time.sleep(1)
            if profile.get('state') != 'bound':
                raise ValueError('Камера не подтвердила вход: ' + profile.get('state', 'unknown'))
            result.update(state='verified', assessment=profile.get('assessment', {}))
    except Exception as exc:
        # Fixed exceptions only; credentials never enter these diagnostics.
        result['error'] = str(exc)[:400]
        result['error_type'] = type(exc).__name__
        if os.environ.get('FIT_LAB_RADIO_CHECK') == '1':
            atomic_write(root / 'logs/camera-radio-readback.json', json.dumps(result).encode())
        if os.environ.get('FIT_LAB_AUDIO_CHECK') == '1':
            atomic_write(root / 'logs/camera-audio-check.json', json.dumps(result).encode())
    atomic_write(target, json.dumps(result, ensure_ascii=False).encode())
    return 0 if result['state'] in ('verified', 'security_saved') else 1
