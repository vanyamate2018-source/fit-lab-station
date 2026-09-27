import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock, patch

import pytest
from master.camera_security import protect_operation
from master.camera_security_remote import guardian, apply_script, commit_script
from master.camera_credentials import CameraCredentialStore, security_receipt_path
from tests.test_camera_credentials import Vault


def test_rotation_vault_requires_persistence_and_keeps_common_password(tmp_path):
    backend = Vault()
    store = CameraCredentialStore(tmp_path, backend)
    store.remember('a', ('root', 'old'))
    store.durable_write('rotation-new:a', ('root', 'new'))
    receipt = security_receipt_path(tmp_path, 'a')
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'stage': 'pending'}))
    assert store.candidates('a') == [('root', 'old'), ('root', 'new')]
    store.durable_write('camera:a', ('root', 'new'))
    assert store.load('unknown') == ('root', 'old')
    backend.fitlab_credential_write = Mock(return_value=-1)
    with pytest.raises(OSError):
        store.durable_write('rotation-new:a', ('root', 'must-not-apply'))


def test_password_rotation_refuses_radio_before_connecting(tmp_path):
    with patch('master.camera_security.connect_camera') as connect:
        with pytest.raises(ValueError, match='LAN'):
            protect_operation('192.168.1.10', 'root', 'secret', tmp_path, 'SHA256:test', transport='radio')
    connect.assert_not_called()


def test_no_remote_write_when_secure_storage_fails(tmp_path):
    client = Mock()
    vault = Mock(storage_name="test-secure-vault")
    vault.durable_write.side_effect = OSError('vault locked')
    with patch('master.camera_security.connect_camera', return_value=client), \
         patch('master.camera_security.check_identity'), patch('master.camera_security.preflight'), \
         patch('master.camera_security.read_settings', return_value={'config': {'system': {'unsafe': False}}}), \
         patch('master.camera_security.CameraCredentialStore', return_value=vault), \
         patch('master.camera_security.upload') as upload, patch('master.camera_security.send_password') as send:
        with pytest.raises(ValueError):
            protect_operation('192.168.1.10', 'root', 'secret', tmp_path, 'SHA256:test')
    upload.assert_not_called()
    send.assert_not_called()


@pytest.fixture
def remote(tmp_path):
    base = tmp_path / 'security'
    base.mkdir()
    shadow = tmp_path / 'shadow'
    shadow.write_text('root:oldhash:1:0:99999:7:::\nuser:keep:1:0:99999:7:::\n')
    bins = tmp_path / 'bin'
    bins.mkdir()
    for name in ('flock', 'sync'):
        f = bins / name
        f.write_text('#!/bin/sh\n[ "$1" != "-w" ] || exit 2\nexit 0\n')
        f.chmod(0o700)
    change = bins / 'chpasswd'
    change.write_text(f'''#!{sys.executable}
import sys
from pathlib import Path
p=Path({str(shadow)!r})
user,value=sys.stdin.readline().strip().split(':',1)
value=value if '-e' in sys.argv else 'newhash'
rows=p.read_text().splitlines()
rows=[user+':'+value+':'+':'.join(r.split(':')[2:]) if r.startswith(user+':') else r for r in rows]
p.write_text('\\n'.join(rows)+'\\n')
''')
    change.chmod(0o700)
    guard = base / 'guardian.sh'
    guard.write_text(guardian(str(base), str(shadow), str(change)))
    env = dict(os.environ, PATH=str(bins)+':'+os.environ['PATH'])
    return base, shadow, change, guard, env


def test_password_change_without_commit_is_rolled_back_and_leaks_no_secret(remote):
    base, shadow, change, guard, env = remote
    ticket = 'a'*32
    result = subprocess.run(['/bin/sh', '-c', apply_script(ticket, str(base), str(shadow), str(change), wait=1)],
                            input='Secret_for_test_123456789012345678\n', text=True, capture_output=True, env=env, timeout=5)
    assert result.returncode == 0
    assert result.stdout.strip() == 'applied'
    deadline = time.monotonic()+4
    while (base/'pending').exists() and time.monotonic()<deadline:
        time.sleep(.05)
    assert 'root:oldhash:' in shadow.read_text()
    assert 'user:keep:' in shadow.read_text()
    assert (base/ticket/'state').read_text().strip() == 'rolled_back'
    assert not (base/ticket/'previous.hash').exists()
    assert not any('Secret_for_test' in f.read_text() for f in base.rglob('*') if f.is_file())


def test_boot_guard_preserves_later_external_password_and_marks_conflict(remote):
    base, shadow, change, guard, env = remote
    ticket = 'b'*32
    op=base/ticket;op.mkdir()
    (base/'pending').write_text(ticket)
    (op/'state').write_text('applied')
    (op/'previous.hash').write_text('oldhash')
    (op/'new.hash').write_text('transactionhash')
    result=subprocess.run(['/bin/sh',str(guard),'boot'],env=env,capture_output=True,timeout=5)
    # Existing old hash is a valid rollback target, so simulate an outside change.
    shadow.write_text('root:outsidehash:1:0:99999:7:::\n')
    (base/'pending').write_text(ticket)
    (op/'previous.hash').write_text('oldhash');(op/'new.hash').write_text('transactionhash')
    result=subprocess.run(['/bin/sh',str(guard),'boot'],env=env,capture_output=True,timeout=5)
    assert result.returncode != 0
    assert 'outsidehash' in shadow.read_text()
    assert (op/'state').read_text().strip() == 'conflict'


def test_rollback_cannot_cancel_another_transaction(remote):
    base, shadow, change, guard, env = remote
    (base/'pending').write_text('a'*32)
    result=subprocess.run(['/bin/sh',str(guard),'rollback','0','b'*32],env=env,capture_output=True,timeout=5)
    assert result.returncode != 0
    assert (base/'pending').read_text() == 'a'*32


def test_confirmed_change_survives_watchdog_and_cleans_hash_backups(remote):
    base, shadow, change, guard, env = remote
    ticket = 'c'*32
    result = subprocess.run(['/bin/sh', '-c', apply_script(ticket, str(base), str(shadow), str(change), wait=1)],
        input='Secret_for_test_123456789012345678\n', text=True, capture_output=True, env=env, timeout=5)
    assert result.returncode == 0
    result = subprocess.run(['/bin/sh', '-c', commit_script(ticket, str(base), str(shadow))],
                            text=True, capture_output=True, env=env, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == 'committed'
    time.sleep(1.1)
    assert 'root:newhash:' in shadow.read_text()
    assert not (base/'pending').exists()
    assert not (base/ticket/'previous.hash').exists()
    assert (base/ticket/'state').read_text().strip() == 'committed'


def test_rotation_confirms_new_login_rejects_old_then_commits(tmp_path):
    import paramiko
    initial, verified = Mock(), Mock()
    vault = Mock(storage_name="test-secure-vault")
    with patch('master.camera_security.connect_camera', side_effect=[initial, verified, paramiko.AuthenticationException()]), \
         patch('master.camera_security.check_identity'), patch('master.camera_security.preflight'), \
         patch('master.camera_security.CameraCredentialStore', return_value=vault), \
         patch('master.camera_security.upload'), patch('master.camera_security.send_password'), \
         patch('master.camera_security.read_settings', return_value={'config': {'system': {'unsafe': False}}}), patch('master.camera_security.checked') as checked:
        result = protect_operation('192.168.1.10', 'root', 'old', tmp_path, 'SHA256:test')
    assert result['state'] == 'security_saved'
    assert result['security']['old_password_rejected'] is True
    assert vault.durable_write.call_count == 3
    assert 'committed' in checked.call_args.args[1]
    assert not any('old' == v for v in result['security'].values())
