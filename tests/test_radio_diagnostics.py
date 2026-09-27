import subprocess
from unittest.mock import patch

import pytest

from master.camera_radio import command_sections, radio_operation


@pytest.mark.parametrize('case,supported', [('start|stop)',True),('start|stop|prepare)',True),
                                           ('reset|prepare)',False),('# start|stop)',False)])
def test_service_detection_accepts_verified_prepare_variant(tmp_path,case,supported):
    from master.camera_radio import SERVICE_CAPABILITIES
    script=tmp_path/'service'
    # A minimal valid script: unsupported labels must not grant restart access.
    script.write_text('#!/bin/sh\n# /etc/wfb.yaml\nstart_broadcast() { :; }\ncase "$1" in\n'
                      + (case+'\n :;;\n' if not case.startswith('#') else case+'\nother) :;;\n')
                      +'cli) :;;\nesac\n')
    command=SERVICE_CAPABILITIES.replace('service=$(command -v wifibroadcast)', 'service='+str(script))
    command=command.replace('/usr/bin/wifibroadcast|/usr/sbin/wifibroadcast|/sbin/wifibroadcast)',str(script)+')')
    result=subprocess.run(['sh','-c',command],capture_output=True,text=True,check=True)
    assert ('start|stop)' in result.stdout)==supported


def test_batched_diagnostics_preserve_empty_output_and_exit_codes():
    def run(_, script, **options):
        result = subprocess.run(['sh', '-c', script], capture_output=True, text=True, timeout=3)
        return result.returncode, result.stdout.strip()
    with patch('master.camera_radio.command', side_effect=run):
        assert command_sections(None, ['true', 'printf "two\\nlines\\n"', 'exit 7']) == [
            (0, ''), (0, 'two\nlines'), (7, '')]


def test_truncated_diagnostics_are_not_interpreted_as_success():
    with patch('master.camera_radio.command', return_value=(0, 'partial response')):
        with pytest.raises(ValueError, match='Неполный'):
            command_sections(None, ['true'])


def test_radio_refresh_does_not_download_firmware_or_full_diagnostics(tmp_path):
    (tmp_path/'logs').mkdir()
    snapshot = {'config':{}, 'live':{}, 'transmitter_running':True}
    with patch('master.camera_api.connect_camera'), \
         patch('master.camera_radio.inspect_radio', return_value=snapshot), \
         patch('master.camera_radio.command', side_effect=AssertionError('bulk download over RF')):
        result = radio_operation('192.168.1.10', 'root', 'test-secret', tmp_path, transport='radio')
    assert result['state'] == 'radio_settings'
