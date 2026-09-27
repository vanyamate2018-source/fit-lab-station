import json
from unittest.mock import Mock, patch
from master.camera_api import MajesticAPI
import pytest


def test_old_accepted_response_without_length_does_not_wait_for_eof():
    client = Mock()
    response = Mock(status=202, length=None)
    response.read.side_effect = AssertionError("old firmware never closes 202 socket")
    connection = Mock()
    connection.getresponse.return_value = response
    with patch('master.camera_api.http.client.HTTPConnection', return_value=connection):
        api = MajesticAPI(client, 'operator', 'test-secret')
        assert api('POST', '/api/v1/config', {'osd': {'enabled': False}}) == {}
    assert api.last_write_response == {'method': 'POST', 'path': '/api/v1/config', 'status': 202}
    payload = connection.request.call_args.args[2]
    assert json.loads(payload) == {'osd': {'enabled': 'false'}}
    assert 'test-secret' not in json.dumps(api.last_write_response)


def test_request_timeout_keeps_write_failure_in_diagnostics():
    connection = Mock()
    connection.getresponse.side_effect = TimeoutError('timed out')
    with patch('master.camera_api.http.client.HTTPConnection', return_value=connection):
        api = MajesticAPI(Mock(), 'operator', 'test-secret')
        try:
            api('POST', '/api/v1/config', {'video0': {'fps': 60}})
        except TimeoutError:
            pass
    assert api.last_write_response is None
    assert api.last_write_error == 'TimeoutError: timed out'
    connection.close.assert_called_once()


def test_legacy_persists_then_applies_url_encoded_leaf():
    api = MajesticAPI(Mock(), 'operator', 'test-secret', legacy=True)
    with patch('master.camera_radio.command', side_effect=[(0, ''), (0, '51')]) as command, patch.object(api, '_request') as request:
        api('POST', '/api/v1/config', {'image': {'saturation': 51}})
    assert [call.args[1] for call in command.call_args_list] == [
        'cli -s .image.saturation 51', 'cli -g .image.saturation']
    request.assert_called_once_with('GET', '/api/v1/set?image.saturation=51', writing=True)


def test_legacy_does_not_apply_runtime_when_save_not_confirmed():
    api = MajesticAPI(Mock(), 'operator', 'test-secret', legacy=True)
    with patch('master.camera_radio.command', side_effect=[(0, ''), (0, '50')]), patch.object(api, '_request') as request:
        with pytest.raises(ValueError, match='не совпадает'):
            api('POST', '/api/v1/config', {'image': {'saturation': 51}})
    request.assert_not_called()


def test_video_failure_restores_only_our_changes_and_restarts_video():
    from master.camera_api import guard_video_service
    api = Mock(return_value={'osd': {'enabled': True}})
    with patch('master.camera_api.video_service_ready', side_effect=[False] * 8 + [True]), \
         patch('master.camera_api.time.sleep'), \
         patch('master.camera_api.apply_checked') as apply, \
         patch('master.camera_radio.command', return_value=(0, '')) as command:
        with pytest.raises(ValueError, match='восстановлены'):
            guard_video_service(Mock(), api, {}, {'osd': {'enabled': False}}, {'osd.enabled': True}, True)
    assert apply.call_args.args[3] == {'osd.enabled': False}
    assert any('S95majestic restart' in call.args[1] for call in command.call_args_list)


def test_video_guard_refuses_to_overwrite_concurrent_camera_edit():
    from master.camera_api import guard_video_service
    api = Mock(return_value={'video0': {'fps': 30}})
    with patch('master.camera_api.video_service_ready', return_value=False), \
         patch('master.camera_api.time.sleep'), patch('master.camera_api.apply_checked') as apply:
        with pytest.raises(ValueError, match='извне'):
            guard_video_service(Mock(), api, {}, {'video0': {'fps': 120}}, {'video0.fps': 60}, True)
    apply.assert_not_called()


def test_radio_proxy_retains_pinned_camera_identity(tmp_path):
    from master.camera_api import connect_camera
    client, relay = Mock(), Mock()
    with patch('paramiko.SSHClient', return_value=client), patch('master.camera_api.control_socket', return_value=relay):
        assert connect_camera('192.168.1.10', 'root', 'test-secret', tmp_path, 'radio') is client
    assert client.connect.call_args.args == ('192.168.1.10',)
    assert client.connect.call_args.kwargs['sock'] is relay
    client.load_host_keys.assert_called_once_with(str(tmp_path/'config/camera_known_hosts'))
    import paramiko
    assert isinstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.RejectPolicy)


def test_restart_waits_for_old_camera_children_before_starting():
    from master.camera_radio import restart_service
    import shlex
    client = Mock()
    with patch('master.camera_radio.command', return_value=(0, '')) as command:
        ticket = restart_service(client, True)
    import base64
    launch = command.call_args.args[1]
    script = b"".join(base64.b64decode(shlex.split(c.args[1])[2]) for c in command.call_args_list if c.args[1].startswith("printf %s ")).decode()
    assert launch.startswith('nohup setsid sh ')
    assert 'wifilink' not in launch and 'wfb_tx' not in launch
    assert script.index('kill -TERM') < script.index('while pidof') < script.index('wifibroadcast start')
    assert 'wifilink' in script and 'done:$result' in script
    assert 'flock -n 9' in script and '2>&1 9>&-' in script
    assert ticket in script and 'mkdir' not in script


def test_lost_restart_reply_is_not_retransmitted():
    from master.camera_radio import restart_service
    import paramiko
    def reply(client, text, **kwargs):
        if text.startswith('nohup setsid'):
            raise paramiko.SSHException('Channel closed')
        return 0, ''
    with patch('master.camera_radio.command', side_effect=reply) as command:
        ticket = restart_service(Mock(), True)
    assert ticket.startswith('/tmp/fit-lab-radio-')
    assert sum('nohup setsid' in call.args[1] for call in command.call_args_list) == 1


def test_radio_frequency_is_only_prepared_before_master_arms_it(tmp_path):
    from master.camera_radio import radio_operation
    (tmp_path/'logs').mkdir()
    snapshot={'config':{'channel':108,'width':20,'power':18},'live':{'channel':108,'width':20},
              'channels':[36,108],'restart_ready':True,'adaptive':False,'backend':'yaml','transmitter_running':True}
    prepared={'ticket':'/tmp/fit-lab-radio-'+'a'*32}
    with patch('master.camera_api.connect_camera'), patch('master.camera_radio.inspect_radio',return_value=snapshot), \
         patch('master.radio_switch.prepare_switch',return_value=prepared) as prepare, \
         patch('master.camera_radio.restart_service') as restart:
        result=radio_operation('192.168.1.10','root','test-secret',tmp_path,channel=36,baseline=snapshot,transport='radio')
    assert result['state']=='radio_prepared'
    assert prepare.call_args.args[2]=={'channel':36}
    restart.assert_not_called()


def test_only_pre_auth_handshake_is_retried():
    from unittest.mock import Mock, patch
    import paramiko
    from master.camera_api import connect_camera
    client = Mock()
    with patch('master.camera_api._connect_camera_once', side_effect=[paramiko.SSHException('No existing session'), client]) as connect, patch('master.camera_api.time.sleep'):
        assert connect_camera('192.168.1.10', 'root', 'secret', 'data') is client
        assert connect.call_count == 2
    for error in (paramiko.AuthenticationException('denied'), paramiko.SSHException('По радио ответила другая камера')):
        with patch('master.camera_api._connect_camera_once', side_effect=error) as connect, patch('master.camera_api.time.sleep'):
            with pytest.raises(paramiko.SSHException):
                connect_camera('192.168.1.10', 'root', 'secret', 'data')
            assert connect.call_count == 1


def test_radio_connect_timeout_retries_before_any_command():
    import socket
    from unittest.mock import Mock, patch
    from master.camera_api import connect_camera
    client = Mock()
    with patch('master.camera_api._connect_camera_once', side_effect=[socket.timeout(), client]) as connect, patch('master.camera_api.time.sleep'):
        assert connect_camera('192.168.1.10', 'root', 'secret', 'data', 'radio') is client
        assert connect.call_count == 2
    with patch('master.camera_api._connect_camera_once', side_effect=socket.timeout()) as connect, patch('master.camera_api.time.sleep'):
        with pytest.raises(socket.timeout):
            connect_camera('192.168.1.10', 'root', 'secret', 'data', 'radio')
        assert connect.call_count == 3
