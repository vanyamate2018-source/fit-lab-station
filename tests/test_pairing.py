import json
import os
from pathlib import Path
import subprocess
import sys
import time

from nacl.public import Box, PrivateKey, PublicKey
import pytest
from shared.pairing_store import PairingStore
from master.pairing_remote import activation_script, boot_script


def test_generated_wfb_pair_encrypts_both_directions_and_receipt_is_public(tmp_path):
    store = PairingStore(tmp_path / 'data')
    receipt = store.create('a'*24, '192.168.1.10', 'public-ssh-fingerprint')
    folder = store.folder(receipt['ticket'])
    gs, drone = [(folder / name).read_bytes() for name in ('gs.key', 'drone.key')]
    ground = Box(PrivateKey(gs[:32]), PublicKey(gs[32:]))
    camera = Box(PrivateKey(drone[:32]), PublicKey(drone[32:]))
    assert camera.decrypt(ground.encrypt(b'command')) == b'command'
    assert ground.decrypt(camera.encrypt(b'video')) == b'video'
    assert len(gs) == len(drone) == 64 and gs != drone
    assert (folder / 'gs.key').stat().st_mode & 0o777 == 0o600
    encoded = json.dumps(receipt)
    assert gs.hex() not in encoded and drone.hex() not in encoded
    with pytest.raises(ValueError):
        store.create('b'*24, '192.168.1.11', 'other')


def test_crash_receipt_blocks_normal_rx_and_rollback_restores_exact_old_key(tmp_path, monkeypatch):
    store = PairingStore(tmp_path / 'data')
    store.active_key.parent.mkdir(parents=True)
    store.active_key.write_bytes(b'o'*64)
    receipt = store.create('a'*24, 'camera', 'fp')
    store.activate(receipt)
    assert store.active_key.read_bytes() != b'o'*64
    with pytest.raises(ValueError): store.guard()
    monkeypatch.setenv('FIT_LAB_PAIRING_ID', receipt['ticket'])
    store.guard()
    store.finish(receipt, False)
    assert store.active_key.read_bytes() == b'o'*64 and store.pending() is None


@pytest.fixture
def remote(tmp_path):
    base, key = tmp_path / 'remote', tmp_path / 'drone.key'
    ticket = 'a'*32
    op = base / ticket
    op.mkdir(parents=True)
    key.write_bytes(b'o'*64)
    (op / 'new.key').write_bytes(b'n'*64)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    flock = bin_dir / 'flock'
    flock.write_text(f'#!{sys.executable}\nimport fcntl,sys\ntry: fcntl.flock(int(sys.argv[-1]),fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: sys.exit(75)\n')
    flock.chmod(0o700)
    env = {**os.environ, 'PATH': str(bin_dir)+':'+os.environ['PATH']}
    script = activation_script(ticket, base=str(base), key=str(key), restart='true', ticks=8)
    script = script.replace('/tmp/fit-lab-radio.flock', str(tmp_path/'lock'))
    return base, key, op, script, env


def test_watchdog_without_commit_restores_original_camera_key(remote):
    base, key, op, script, env = remote
    run = subprocess.run(['sh', '-c', script], env=env, timeout=5)
    assert run.returncode != 0
    assert key.read_bytes() == b'o'*64
    assert (op/'status').read_text().strip() == 'rolled_back'
    assert not (base/'pending').exists()


def test_commit_is_durable_and_repeated_activation_does_not_rotate_again(remote):
    base, key, op, script, env = remote
    process = subprocess.Popen(['sh','-c',script], env=env)
    try:
        deadline = time.monotonic()+3
        while time.monotonic()<deadline:
            if (op/'status').exists() and (op/'status').read_text().strip()=='verifying': break
            time.sleep(.01)
        (op/'commit').write_text(op.name)
        assert process.wait(timeout=3)==0
        assert key.read_bytes()==b'n'*64 and not (base/'pending').exists()
        assert subprocess.run(['sh','-c',script],env=env,timeout=3).returncode==0
        assert (op/'previous.key').read_bytes()==b'o'*64
        assert (op/'status').read_text().strip()=='committed'
    finally:
        if process.poll() is None: process.kill();process.wait()


def test_boot_restores_unfinished_pairing_but_keeps_committed_key(remote, tmp_path):
    base,key,op,_,env=remote
    (op/'previous.key').write_bytes(b'o'*64)
    key.write_bytes(b'n'*64)
    (base/'pending').write_text(op.name)
    (op/'status').write_text('verifying')
    path=tmp_path/'boot.sh'
    path.write_text(boot_script(str(base),str(key)))
    assert subprocess.run(['sh',str(path),'start'],env=env,timeout=3).returncode==0
    assert key.read_bytes()==b'o'*64
    key.write_bytes(b'n'*64)
    (base/'pending').write_text(op.name)
    (op/'status').write_text('committed')
    subprocess.run(['sh',str(path),'start'],env=env,check=True,timeout=3)
    assert key.read_bytes()==b'n'*64
