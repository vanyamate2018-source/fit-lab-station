"""Exercise the generated remote transaction against isolated fake hardware."""
import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from master.camera_radio import transaction_script


@pytest.fixture
def camera(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    state = tmp_path / 'power'
    state.write_text('18')
    commands = {
        'flock': f'#!{sys.executable}\nimport fcntl,sys\ntry: fcntl.flock(int(sys.argv[-1]),fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: sys.exit(75)\n',
        'wifibroadcast': '#!/bin/sh\nif [ "$2" = "-g" ]; then cat "$TEST_STATE"; else printf %s "$4" > "$TEST_STATE"; fi\n',
        'iw': '#!/bin/sh\necho "$*" >> "$TEST_IW"\n',
    }
    for name, text in commands.items():
        target = bin_dir / name
        target.write_text(text)
        target.chmod(0o700)
    env = {**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'],
           'TEST_STATE': str(state), 'TEST_IW': str(tmp_path / 'iw.log')}
    ticket, lock = tmp_path / 'receipt', tmp_path / 'lock'
    snapshot = {'config': {'power': 18}, 'driver': 'rtl88x2eu', 'power_scale': .5,
                'transmitter_running': True}
    script, live = transaction_script(str(ticket), False, snapshot, {'txpower': 20})
    assert live
    script = script.replace('/tmp/fit-lab-radio.flock', str(lock))
    return tmp_path, state, env, ticket, lock, script


def test_busy_camera_changes_neither_persistent_nor_live_power(camera):
    root, state, env, ticket, lock, script = camera
    with lock.open('w') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(['sh', '-c', script], env=env, timeout=5)
    assert result.returncode == 75
    assert ticket.read_text().strip() == 'busy'
    assert state.read_text() == '18'
    assert not (root / 'iw.log').exists()


def test_conflict_is_rejected_before_persisting_anything(camera):
    root, state, env, ticket, lock, script = camera
    state.write_text('22')
    result = subprocess.run(['sh', '-c', script], env=env, timeout=5)
    assert result.returncode != 0
    assert ticket.read_text().strip() == 'conflict'
    assert state.read_text() == '22'
    assert not (root / 'iw.log').exists()


def test_live_power_persists_and_applies_without_service_stop(camera):
    root, state, env, ticket, lock, script = camera
    result = subprocess.run(['sh', '-c', script], env=env, timeout=5)
    assert result.returncode == 0
    assert ticket.read_text().strip() == 'done:0'
    assert state.read_text() == '20'
    assert (root / 'iw.log').read_text().strip() == 'dev wlan0 set txpower fixed 1000'
    with lock.open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_signal_releases_lock_and_records_failure(camera):
    root, state, env, ticket, lock, script = camera
    # A deterministic self-signal while the transaction owns its lock.
    script = script.replace('echo saving', 'kill -TERM $$\necho saving')
    result = subprocess.run(['sh', '-c', script], env=env, timeout=5)
    assert result.returncode != 0
    assert ticket.read_text().strip() == 'interrupted'
    assert state.read_text() == '18'
    with lock.open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_service_children_do_not_inherit_lock_and_kills_are_targeted():
    script, live = transaction_script('/tmp/test-receipt', True)
    assert not live
    assert 'cat /proc/$pid/comm' in script
    assert 'kill -TERM "$pid"' in script
    assert 'killall' not in script
    assert 'wifibroadcast start </dev/null >/dev/null 2>&1 9>&-' in script


@pytest.mark.parametrize('vendor_key, saved, actual', [('fps', '30', '60'), ('Size', '1280x720', '1920x1080')])
def test_service_restart_cannot_silently_restore_old_sd_video_mode(camera, vendor_key, saved, actual):
    root, state, env, ticket, lock, _ = camera
    config = root / 'sd.ini'
    before = f'{vendor_key}={saved}\n'
    config.write_text(before)
    cli = root / 'bin/cli'
    cli.write_text(f'#!/bin/sh\nprintf {actual}\n')
    cli.chmod(0o700)
    snapshot = {'vendor_ini': {str(config): {
        'digest': hashlib.sha256(config.read_bytes()).hexdigest(), 'values': {vendor_key: saved}}}}
    script, live = transaction_script(str(ticket), True, snapshot)
    assert not live
    script = script.replace('/tmp/fit-lab-radio.flock', str(lock))
    result = subprocess.run(['sh', '-c', script], env=env, timeout=5)
    assert result.returncode != 0
    assert ticket.read_text().strip() == 'video_conflict'
    assert config.read_text() == before
    assert not (root / 'iw.log').exists()
