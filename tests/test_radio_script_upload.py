import base64
import shlex
from unittest.mock import patch
import pytest
from master.camera_radio import launch_script


def test_large_script_uses_bounded_chunks_and_verifies_before_launch():
    script = "echo 'quoted value'\n" * 1000
    commands=[]
    with patch('master.camera_radio.command', side_effect=lambda client, text, **kw: (commands.append(text) or (0,''))):
        launch_script(None,'/tmp/fit-lab-radio-'+'a'*32,script)
    assert max(len(c.encode()) for c in commands)<2000
    blocks=[shlex.split(c)[2] for c in commands if c.startswith('printf %s ')]
    assert b''.join(base64.b64decode(b) for b in blocks)==script.encode()
    assert 'sha256sum' in commands[-2]
    assert commands[-1].startswith('nohup setsid sh ')


def test_failed_upload_never_launches():
    commands=[]
    def command(client,text,**kw):
        commands.append(text)
        return (1 if text.startswith('printf') else 0),' '
    with patch('master.camera_radio.command',side_effect=command),pytest.raises(ValueError):
        launch_script(None,'/tmp/fit-lab-radio-'+'a'*32,'echo test')
    assert not any(c.startswith('nohup') for c in commands)
