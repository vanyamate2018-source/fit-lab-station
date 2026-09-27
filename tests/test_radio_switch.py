import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock, patch

import pytest

from master.radio_switch import coordinated_script, valid_ticket


@pytest.fixture
def switching_camera(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for key, value in [('channel','108'),('width','20'),('txpower','18')]:
        (tmp_path/key).write_text(value)
    commands = {
        'flock': f'#!{sys.executable}\nimport fcntl,sys\ntry: fcntl.flock(int(sys.argv[-1]),fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: sys.exit(75)\n',
        'sleep': f'#!{sys.executable}\nimport time\ntime.sleep(.005)\n',
        'wifibroadcast': '#!/bin/sh\nk=${3##*.}\nif [ "$2" = "-g" ]; then cat "$TEST_DIR/$k"; else printf %s "$4" > "$TEST_DIR/$k"; fi\n',
        'iw': '#!/bin/sh\necho "$*" >> "$TEST_DIR/iw.log"\n',
    }
    for name, text in commands.items():
        p=bin_dir/name; p.write_text(text); p.chmod(0o700)
    snapshot={'config':{'channel':108,'width':20,'power':18},
              'live':{'channel':108,'width':20,'driver_dbm':9},
              'driver':'rtl88x2eu','power_scale':.5,'transmitter_running':True}
    ticket=tmp_path/'receipt'
    valid='/tmp/fit-lab-radio-'+'a'*32
    script=coordinated_script(valid,snapshot,{'channel':36},arm_seconds=3,confirm_seconds=2)
    script=script.replace(valid,str(ticket)).replace('/tmp/fit-lab-radio.flock',str(tmp_path/'lock'))
    env={**os.environ,'PATH':str(bin_dir)+':'+os.environ['PATH'],'TEST_DIR':str(tmp_path)}
    def launch():
        return subprocess.Popen(['sh','-c',script],env=env)
    return tmp_path,ticket,launch


def wait_stage(ticket, expected):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        if ticket.exists() and ticket.read_text().strip()==expected:
            return
        time.sleep(.005)
    raise AssertionError(ticket.read_text() if ticket.exists() else 'no receipt')


def test_unarmed_switch_never_changes_camera(switching_camera):
    root,ticket,launch=switching_camera
    process=launch(); process.wait(timeout=8)
    assert ticket.read_text().strip()=='expired'
    assert (root/'channel').read_text()=='108'
    assert not (root/'iw.log').exists()


def test_lost_confirmation_restores_channel_automatically(switching_camera):
    root,ticket,launch=switching_camera
    process=launch(); wait_stage(ticket,'prepared')
    Path(str(ticket)+'.arm').touch()
    process.wait(timeout=8)
    assert ticket.read_text().strip()=='rolled_back'
    assert (root/'channel').read_text()=='108'
    actions=(root/'iw.log').read_text()
    assert 'set channel 36 HT20' in actions and 'set channel 108 HT20' in actions


def test_confirmed_new_channel_is_kept(switching_camera):
    root,ticket,launch=switching_camera
    process=launch(); wait_stage(ticket,'prepared')
    Path(str(ticket)+'.arm').touch(); wait_stage(ticket,'awaiting_ack')
    Path(str(ticket)+'.decision').symlink_to('commit')
    process.wait(timeout=8)
    assert ticket.read_text().strip()=='done:0'
    assert (root/'channel').read_text()=='36'
    assert 'set channel 108' not in (root/'iw.log').read_text()


def test_external_change_during_arm_wait_is_not_overwritten(switching_camera):
    root,ticket,launch=switching_camera
    process=launch(); wait_stage(ticket,'prepared')
    (root/'channel').write_text('40')
    Path(str(ticket)+'.arm').touch()
    process.wait(timeout=8)
    assert ticket.read_text().strip()=='conflict'
    assert (root/'channel').read_text()=='40'
    assert not (root/'iw.log').exists()


def test_driver_failure_after_retune_rolls_back_persistent_and_live_channel(switching_camera):
    root,ticket,launch=switching_camera
    iw=root/'bin/iw'
    iw.write_text('#!/bin/sh\necho "$*" >> "$TEST_DIR/iw.log"\n[ "$5" != 36 ]\n')
    process=launch(); wait_stage(ticket,'prepared')
    Path(str(ticket)+'.arm').touch()
    process.wait(timeout=8)
    assert ticket.read_text().strip()=='rolled_back'
    assert (root/'channel').read_text()=='108'
    assert 'set channel 108 HT20' in (root/'iw.log').read_text()


def test_ticket_cannot_select_arbitrary_remote_path():
    for ticket in ('/etc/user.ini','/tmp/fit-lab-radio-x; reboot',None):
        with pytest.raises(ValueError): valid_ticket(ticket)


@pytest.fixture
def radio_rpc(tmp_path):
    from master.radio_switch import switch_operation
    ticket = '/tmp/fit-lab-radio-' + 'a' * 32
    snapshot = {'live': {'channel': 108, 'width': 20, 'driver_dbm': 9},
                'config': {'channel': 108, 'width': 20, 'power': 18},
                'power_scale': .5, 'transmitter_running': True}
    with patch('master.camera_api.connect_camera') as connect, \
         patch('master.radio_switch.command') as command, \
         patch('master.radio_switch.inspect_radio', return_value=snapshot) as inspect, \
         patch('master.diagnostics.append_event') as audit, patch('master.radio_switch.time.sleep'):
        def run(stage, action='query', target=None):
            command.return_value = (0, stage)
            return switch_operation('192.168.1.10', 'root', 'test-secret', tmp_path, ticket,
                                    action, target or {'channel': 108, 'width': 20, 'driver_dbm': 9})
        yield run, command, inspect, snapshot, connect.return_value, audit


@pytest.mark.parametrize('stage', ['saving', 'applying', 'stopping', 'starting', 'awaiting_ack', 'done:0'])
def test_retry_after_lost_arm_reply_rejoins_without_replaying_write(radio_rpc, stage):
    run, command, inspect, _, client, audit = radio_rpc
    assert run(stage, 'arm')['state'] == 'radio_armed'
    assert command.call_count == 1 and command.call_args.args[1].startswith('cat ')
    inspect.assert_not_called()
    client.close.assert_called_once()
    assert audit.call_args.args[1]['result'] == 'already_armed'


@pytest.mark.parametrize('stage', ['save_failed', 'apply_failed', 'stop_timeout', 'rollback_conflict', 'video_conflict', 'done:1'])
def test_terminal_failure_returns_readback_instead_of_pending_forever(radio_rpc, stage):
    run, _, inspect, snapshot, _, _ = radio_rpc
    result = run(stage)
    assert result['state'] == 'radio_switch_failed'
    assert result['radio_settings'] is snapshot
    assert result['stage'] == stage and result['error']
    inspect.assert_called_once()


def test_expired_arm_returns_actual_channel_without_rearming(radio_rpc):
    run, command, _, snapshot, _, _ = radio_rpc
    result = run('expired', 'arm')
    assert result['state'] == 'radio_rolled_back' and result['radio_settings'] is snapshot
    assert command.call_count == 1


def test_lost_commit_reply_is_confirmed_only_after_live_and_saved_readback(radio_rpc):
    run, command, _, snapshot, _, _ = radio_rpc
    assert run('done:0')['state'] == 'radio_switch_confirmed'
    snapshot['config']['power'] = 20
    result = run('done:0')
    assert result['state'] == 'radio_switch_failed'
    assert result['stage'] == 'readback_mismatch'
    assert command.call_count == 2  # No write is replayed.


def test_stopped_transmitter_is_never_confirmed_from_old_receipt(radio_rpc):
    run, _, _, snapshot, _, _ = radio_rpc
    snapshot['transmitter_running'] = False
    assert run('done:0')['state'] == 'radio_switch_failed'


def test_commit_reads_back_after_watchdog_wins_race(radio_rpc):
    run, command, inspect, snapshot, _, _ = radio_rpc
    old = {**snapshot, 'live': {**snapshot['live'], 'channel': 100}}
    inspect.side_effect = [snapshot, old]
    command.side_effect = [(0, 'awaiting_ack'), (0, ''), (0, 'rolled_back')]
    result = run('awaiting_ack', 'commit')
    assert result['state'] == 'radio_rolled_back'
    assert result['radio_settings']['live']['channel'] == 100


def test_commit_rejects_persistent_mismatch_without_sending_vote(radio_rpc):
    run, command, _, snapshot, _, audit = radio_rpc
    snapshot['config']['channel'] = 100
    with pytest.raises(ValueError, match='не подтверждены'):
        run('awaiting_ack', 'commit')
    assert command.call_count == 1
    assert audit.call_args.args[1]['result'] == 'unconfirmed'


def test_exhausted_channel_scan_can_be_retried_without_replaying_settings():
    from types import SimpleNamespace, MethodType
    from master.ui.main_window import MainWindow
    window = SimpleNamespace(
        radio_switch={'deadline': 0, 'fallbacks': 2, 'phase': 'armed'},
        camera=SimpleNamespace(closed=False, credentials=('root', 'test-secret'), read_radio=Mock()),
        session=SimpleNamespace(running=True), radio_editor=Mock(), radio_switch_timer=Mock(), notify=Mock())
    window._wait_radio_recovery = MethodType(MainWindow._wait_radio_recovery, window)
    MainWindow._tick_radio_switch(window)
    assert window.radio_switch['phase'] == 'recovery'
    assert window.radio_switch['deadline'] == float('inf')
    window.radio_editor.refresh.setEnabled.assert_called_with(True)
    MainWindow._refresh_radio(window)
    assert window.radio_switch['fallbacks'] == 0
    assert window.radio_switch['deadline'] < float('inf')
    window.radio_switch_timer.start.assert_called_once()
    window.camera.read_radio.assert_not_called()
