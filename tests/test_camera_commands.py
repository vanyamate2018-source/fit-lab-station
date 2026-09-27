import json
from threading import Event
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal
from master.camera import CameraManager


class ControlledJob(QObject):
    result = Signal(dict)
    finished = Signal()

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def start(self):
        pass

    def complete(self, value=None):
        self.result.emit(self.operation() if value is None else value)
        self.finished.emit()


@pytest.fixture
def manager(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    with patch('master.camera.QTimer.singleShot'), patch('master.camera.CameraJob', ControlledJob):
        manager = CameraManager(tmp_path)
        manager.timer.stop()
        manager.credentials = ('operator', 'never-log-this')
        manager.bound_host = manager.host
        manager.settings = {'config': {'video0': {'fps': 60}}}
        yield manager
        manager.closed = True
        manager._invalidate('test cleanup')
        manager.deleteLater()


def test_missed_echo_cancels_queue_but_preserves_authenticated_write_readback(manager):
    manager.transport = 'radio'
    manager.radio_connected = True
    events, results = [], []
    manager.commandChanged.connect(events.append)
    manager.changed.connect(results.append)
    active, queued = Mock(), Mock()
    manager._run(active, user=True, label='Запись', writing=True)
    old_job = manager.job
    manager._run(queued, user=True, label='Запись 2', writing=True)
    manager.radio_connected = False
    manager.radio_connected = True
    old_job.complete({'state': 'settings_saved', 'settings': {'config': {'video0': {'fps': 30}}}})
    queued.assert_not_called()
    assert manager.settings['config']['video0']['fps'] == 30
    assert results[-1]['state'] == 'settings_saved'
    assert [e['command_state'] for e in events] == ['running', 'queued', 'cancelled', 'confirmed']
    assert manager.job is None


def test_background_scan_does_not_block_login_but_writes_do(manager):
    manager._run(Mock())
    assert manager.busy and not manager.user_busy
    manager._run(Mock(),user=True,label='Подключение камеры')
    assert manager.user_busy
    assert manager.active_request.cancel.is_set()
    manager.job.complete({'state':'offline'})
    assert manager.user_busy
    manager.job.complete({'state':'auth_required'})
    assert not manager.user_busy


@pytest.mark.parametrize('kind', ['request', 'lan_search'])
def test_close_at_job_disposal_never_waits_on_deleted_thread(manager, kind):
    if kind == 'request':
        manager._run(Mock(), user=True, label='Read')
        job = manager.job
    else:
        manager.transport = 'radio'
        manager.scan()
        job = manager.lan_job
    # Qt may dispose a finished worker before a pending application close.
    # Re-enter close at disposal: ownership must already be cleared.
    job.deleteLater = Mock(side_effect=manager.close)
    job.complete({'state': 'offline'})
    assert manager.closed
    assert manager.job is None and manager.lan_job is None
    job.deleteLater.assert_called_once()


def test_missed_echo_does_not_lose_prepared_ticket_or_replay_radio_write(manager):
    manager.transport = 'radio'
    manager.radio_connected = True
    operation = Mock()
    manager._run(operation, user=True, label='Radio', writing=True)
    request = manager.active_request
    manager.radio_connected = False
    assert not request.cancel.is_set()
    ticket = '/tmp/fit-lab-radio-' + 'a' * 32
    manager.job.complete({'state': 'radio_prepared', 'switch': {'ticket': ticket}})
    assert manager.coordinated_ticket == ticket
    assert manager.job is None
    operation.assert_not_called()  # Completion was supplied; no retry was started.


def test_changed_camera_still_discards_late_success_of_active_write(manager):
    manager._run(Mock(), user=True, label='Write', writing=True)
    old = manager.job
    manager.host = '192.168.1.20'
    old.complete({'state': 'settings_saved', 'settings': {'config': {'video0': {'fps': 30}}}})
    assert manager.settings is None


def test_expired_queued_write_never_runs(manager):
    queued = Mock()
    manager._run(lambda _: {'state': 'settings', 'settings': manager.settings}, user=True, label='Read')
    manager._run(queued, user=True, label='Write', writing=True)
    manager.pending_job.expires_at = 0
    manager.job.complete()
    queued.assert_not_called()
    assert manager.job is None


def test_missed_heartbeat_allows_authenticated_read_but_discards_queued_write(manager):
    manager.transport = 'radio'
    manager.radio_connected = True
    results = []
    manager.changed.connect(results.append)
    manager._run(Mock(), user=True, label='Read')
    pending = Mock()
    manager._run(pending, user=True, label='Write', writing=True)
    manager.radio_connected = False
    assert not manager.active_request.cancel.is_set()
    assert manager.pending_job is None
    manager.job.complete({'state': 'settings', 'settings': {'config': {'video0': {'fps': 60}}}})
    assert results[-1]['state'] == 'settings'
    pending.assert_not_called()


@pytest.mark.parametrize('change', ['host', 'transport'])
def test_context_change_cancels_queued_request(manager, change):
    manager._run(lambda _: {}, user=True, label='Read')
    manager._run(Mock(), user=True, label='Write', writing=True)
    old = manager.active_request
    setattr(manager, change, '192.168.1.20' if change == 'host' else 'radio')
    assert old.cancel.is_set()
    assert manager.pending_job is None
    if change == 'host':
        assert manager.credentials is None and manager.settings is None


def test_settings_payload_is_snapshot_and_id_is_audited_without_credentials(manager):
    manager._run(lambda _: {'state': 'found', 'host': manager.host})
    changes = {'video0.fps': 30}
    with patch('master.camera_worker.call', return_value={'state': 'settings_saved', 'settings': {'config': {'video0': {'fps': 30}}}}) as call:
        assert manager.apply_settings(changes)
        request = manager.pending_job
        changes['video0.fps'] = 120
        manager.settings['config']['video0']['fps'] = 50
        manager.job.complete()
        manager.job.complete()
    args = call.call_args.kwargs
    assert args['requested'] == {'video0.fps': 30}
    assert args['baseline'] == {'video0': {'fps': 60}}
    assert args['operation_id'] == request.operation_id
    text = (manager.root/'logs/station-diagnostics.jsonl').read_text()
    assert 'never-log-this' not in text
    events = [json.loads(s) for s in text.splitlines()]
    assert [e['command_state'] for e in events] == ['queued', 'running', 'confirmed']
    assert len({e['operation_id'] for e in events}) == 1


def test_each_bind_uses_its_own_credentials(manager):
    with patch('master.camera.read_profile'):
        assert manager.bind('one', 'first')
        assert manager.bind('two', 'second')
        manager.job.complete({'state': 'bound', 'host': manager.host})
        assert manager.credentials == ('one', 'first')
        manager.job.complete({'state': 'bound', 'host': manager.host})
        assert manager.credentials == ('two', 'second')


@pytest.mark.parametrize('result_state', ['bound', 'auth_required', 'error', 'trust_required'])
def test_saved_login_preserves_authentication_result_and_host_verification(manager, result_state):
    manager.credentials_store = Mock(candidates=Mock(return_value=[('root', 'stored-private')]))
    result = {'state': result_state, 'host': manager.host, 'fingerprint': 'verified-pin'}
    with patch('master.camera.read_profile', return_value=result) as read:
        manager.bind_saved('verified-pin')
        manager.job.complete()
    read.assert_called_once_with(manager.host, 'root', 'stored-private', manager.root, None, 'lan')
    if result_state == 'bound':
        assert manager.credentials == ('root', 'stored-private')
        manager.credentials_store.remember.assert_called_once_with('verified-pin', ('root', 'stored-private'))
    else:
        manager.credentials_store.remember.assert_not_called()
    assert manager.last['state'] == result_state


def test_missing_saved_login_requests_form_without_network_attempt(manager):
    manager.credentials_store = Mock(candidates=Mock(return_value=[]))
    with patch('master.camera.read_profile') as read:
        manager.bind_saved('pin')
        manager.job.complete()
    read.assert_not_called()
    assert manager.last['state'] == 'auth_required'


def test_failed_operation_discards_pending_write(manager):
    manager._run(Mock(), user=True, label='Read')
    pending = Mock()
    manager._run(pending, user=True, label='Write', writing=True)
    manager.job.complete({'state': 'error', 'error': 'Timeout'})
    assert manager.pending_job is None and manager.job is None
    pending.assert_not_called()


def test_no_radio_response_prevents_process_start(manager):
    manager.transport = 'radio'
    operation = Mock()
    assert not manager._run(operation, user=True, label='Write', writing=True)
    operation.assert_not_called()
    assert manager.job is None


def test_repeated_radio_read_is_coalesced_while_active(manager):
    first, duplicate = Mock(), Mock()
    assert manager._run(first, user=True, label='Радионастройки')
    job = manager.job
    assert manager._run(duplicate, user=True, label='Радионастройки')
    assert manager.pending_job is None and manager.job is job
    job.complete({'state': 'radio_settings', 'radio_settings': {}})
    duplicate.assert_not_called()


def test_write_replaces_queued_refresh_but_does_not_preempt_active_job(manager):
    manager._run(Mock(), user=True, label='Чтение настроек')
    active = manager.job
    stale_read = Mock()
    manager._run(stale_read, user=True, label='Радионастройки')
    write = Mock(return_value={'state': 'settings_saved', 'settings': manager.settings})
    assert manager._run(write, user=True, label='Настройки камеры', writing=True)
    assert manager.pending_job.writing and manager.job is active and manager.busy
    active.complete({'state': 'settings', 'settings': manager.settings})
    manager.job.complete()
    stale_read.assert_not_called()
    write.assert_called_once()
    assert not manager.busy


def test_second_write_is_not_allowed_to_replace_first_queued_write(manager):
    manager._run(Mock(), user=True, label='Read')
    first, duplicate = Mock(), Mock()
    assert manager._run(first, user=True, label='Write', writing=True)
    queued = manager.pending_job
    assert not manager._run(duplicate, user=True, label='Write', writing=True)
    assert manager.pending_job is queued


def test_command_records_queue_and_execution_times_without_credentials(manager):
    events = []
    manager.commandChanged.connect(events.append)
    manager._run(Mock(), user=True, label='Read')
    manager._run(Mock(), user=True, label='Write', writing=True)
    manager.pending_job.created_at -= .15
    manager.job.complete({'state': 'settings', 'settings': manager.settings})
    manager.job.complete({'state': 'settings_saved', 'settings': manager.settings})
    last = events[-1]
    assert last['command_state'] == 'confirmed' and last['queue_ms'] >= 150
    assert last['elapsed_ms'] >= last['queue_ms'] and last['execution_ms'] >= 0
    assert 'never-log-this' not in json.dumps(events)


def test_worker_cancellation_before_spawn():
    from master.camera_worker import call
    cancel = Event()
    cancel.set()
    with patch('master.camera_worker.subprocess.Popen') as spawn:
        with pytest.raises(ValueError, match='до отправки'):
            call('settings', '192.168.1.10', 'operator', 'not-logged', None, cancel=cancel)
    spawn.assert_not_called()


def test_worker_disconnect_terminates_local_worker_without_retransmit():
    from master.camera_worker import call
    import subprocess
    cancel = Event()
    process = Mock()
    process.poll.return_value = None
    def communicate(data=None, timeout=None):
        if timeout is not None:
            cancel.set()
            raise subprocess.TimeoutExpired('worker', timeout)
        return b'', b''
    process.communicate.side_effect = communicate
    with patch('master.camera_worker.subprocess.Popen', return_value=process) as spawn:
        with pytest.raises(ValueError, match='могла выполниться'):
            call('settings', '192.168.1.10', 'operator', 'not-logged', None, cancel=cancel)
    spawn.assert_called_once()
    process.kill.assert_called_once()
    assert sum(c.args[0] is not None for c in process.communicate.call_args_list if c.args) == 1


def test_background_discovery_is_idle_when_result_reaches_ui(manager):
    busy = []
    manager.changed.connect(lambda _: busy.append(manager.busy))
    manager._run(lambda _: {'state': 'found', 'host': manager.host})
    manager.job.complete()
    assert busy == [False]


def test_authenticated_profile_initializes_radio_baseline(manager):
    manager.bind('root', 'stored')
    radio = {'hardware_id': 'verified-transmitter', 'live': {'channel': 36}}
    manager.job.complete({'state': 'bound', 'host': manager.host, 'radio_settings': radio})
    assert manager.radio_settings == radio


def test_background_read_error_backs_off_without_user_error(manager):
    results = []
    manager.changed.connect(results.append)
    manager._run(Mock())
    manager.job.complete({'state': 'error', 'error': 'timed out', 'background': True})
    assert manager.sync_retry_after > 0
    assert results == []
    assert manager.job is None
