import os
import subprocess
from unittest.mock import patch
import pytest
from master.pairing import recovery_script


@pytest.mark.parametrize('same_key',[True,False])
def test_service_recovery_keeps_keys_and_refuses_a_different_key(tmp_path,same_key):
    base=tmp_path/'pairing';op=base/('a'*32);op.mkdir(parents=True)
    key=tmp_path/'drone.key';key.write_bytes(b'a'*64 if same_key else b'b'*64)
    (op/'previous.key').write_bytes(b'a'*64)
    (op/'status').write_text('rollback_failed')
    (base/'pending').write_text('a'*32)
    (tmp_path/'system.ok').touch()
    fakebin=tmp_path/'bin';fakebin.mkdir()
    for name in ('flock','pidof'):
        executable=fakebin/name;executable.write_text('#!/bin/sh\nexit 0\n');executable.chmod(0o700)
    with patch('master.pairing.BASE',str(base)),patch('master.pairing.KEY',str(key)),patch('master.pairing.RESTART','true'):
        script=recovery_script(str(op)).replace('/etc/system.ok',str(tmp_path/'system.ok')).replace('/tmp/fit-lab-radio.flock',str(tmp_path/'radio.flock'))
    before=key.read_bytes()
    result=subprocess.run(['sh'],input=script,text=True,capture_output=True,
                          env={**os.environ,'PATH':str(fakebin)+':'+os.environ['PATH']},timeout=3)
    assert key.read_bytes()==before
    assert ((op/'status').read_text().strip()=='rolled_back')==same_key
    assert (base/'pending').exists()!=same_key
    assert (result.returncode==0)==same_key
