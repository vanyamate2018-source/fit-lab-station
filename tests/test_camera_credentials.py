import ctypes
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from master.camera_credentials import CameraCredentialStore
from master.ui.main_window import MainWindow


class Vault:
    def __init__(self):
        self.items = {}

    def fitlab_credential_write(self, account, data, length):
        self.items[account] = ctypes.string_at(data, length)
        return 0

    def fitlab_credential_read(self, account, data, length):
        value = self.items.get(account, b'')
        assert len(value) <= length
        ctypes.memmove(data, value, len(value))
        return len(value)


def test_logins_survive_store_restart_and_different_camera_keeps_own_password(tmp_path):
    vault = Vault()
    first = CameraCredentialStore(tmp_path, vault)
    assert first.load('new') is None
    first.remember('one', ('root', 'common-password'))
    first.remember('two', ('operator', 'different-password'))
    restarted = CameraCredentialStore(tmp_path, vault)
    assert restarted.load('one') == ('root', 'common-password')
    assert restarted.load('two') == ('operator', 'different-password')
    assert restarted.load('new') == ('root', 'common-password')
    assert not list(tmp_path.iterdir())  # No plaintext credential files.


def test_vault_failure_retains_only_session_login_and_never_reports_password(tmp_path):
    vault = Vault()
    vault.fitlab_credential_write = Mock(return_value=-25308)
    store = CameraCredentialStore(tmp_path, vault)
    with pytest.raises(OSError) as error:
        store.remember('camera', ('root', 'private-password'))
    assert 'private-password' not in str(error.value)
    assert store.load('camera') == ('root', 'private-password')


def test_radio_timeout_does_not_open_password_dialog():
    view = SimpleNamespace(login_dialog_open=False, auto_login_pending=False,
        radio_switch=None, camera=SimpleNamespace(transport='radio', radio_connected=False),
        notify=Mock(), _attempt_saved_login=Mock())
    with patch('master.ui.main_window.QDialog') as dialog:
        MainWindow._camera_login(view)
    dialog.assert_not_called()
    view._attempt_saved_login.assert_not_called()


def test_existing_password_is_attempted_before_opening_form():
    view = SimpleNamespace(login_dialog_open=False, auto_login_pending=False,
        radio_switch=None, camera=SimpleNamespace(transport='radio', radio_connected=True, job=None, user_busy=False),
        notify=Mock(), _attempt_saved_login=Mock(return_value=True))
    with patch('master.ui.main_window.QDialog') as dialog:
        MainWindow._camera_login(view)
    view._attempt_saved_login.assert_called_once_with(force=True)
    dialog.assert_not_called()


def test_discovery_does_not_repeat_rejected_login(tmp_path):
    view = SimpleNamespace(auto_login=Mock(isChecked=Mock(return_value=True)),
        auto_login_pending=False, login_dialog_open=False, pairing_requested=False,
        camera=SimpleNamespace(busy=False, user_busy=False, closed=False, transport='radio', radio_connected=True,
            credentials=None, bound_host=None, host='192.168.1.10', bind_saved=Mock(return_value=True)),
        config=SimpleNamespace(data_root=tmp_path), auto_login_attempts=set(), auto_login_retry_at=0, camera_status=Mock())
    assert MainWindow._attempt_saved_login(view)
    view.auto_login_pending = False
    assert not MainWindow._attempt_saved_login(view)
    assert view.camera.bind_saved.call_count == 1


def test_network_failures_retry_without_password_form_and_stop_after_three_attempts():
    context = ('192.168.1.10', 'radio', 'pin')
    view = SimpleNamespace(auto_login_pending=True, auto_login_context=context,
        auto_login_failures={}, auto_login_attempts={context}, auto_login_retry_at=0,
        pairing_requested=False, radio_switch=None, camera_editor=Mock(), radio_editor=Mock(),
        camera_status=Mock(), notify=Mock(), quick_camera_name=Mock(),
        _attempt_saved_login=Mock(), _camera_login=Mock())
    with patch('master.ui.main_window.QTimer.singleShot') as later:
        for attempt in range(3):
            view.auto_login_pending = True
            view.auto_login_attempts.add(context)
            MainWindow._camera_changed(view, {'state': 'error', 'error': 'No existing session'})
    assert later.call_count == 2
    assert all(call.args[1] is view._attempt_saved_login for call in later.call_args_list)
    assert not view.auto_login_pending
    assert context in view.auto_login_attempts
    view._camera_login.assert_not_called()
