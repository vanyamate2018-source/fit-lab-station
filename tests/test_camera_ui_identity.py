from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from master.ui.main_window import MainWindow


def test_rf_auto_selection_does_not_steal_active_lan_setup():
    camera=SimpleNamespace(transport='lan',_lan_available=True,credentials=True,
                           host='192.168.2.148',bound_host='192.168.2.148')
    view=SimpleNamespace(camera=camera)
    MainWindow._radio_camera_selected(view,dict(host='192.168.1.10',ssh_fingerprint='another'))
    assert camera.host=='192.168.2.148' and camera.transport=='lan'


@pytest.mark.parametrize('same', [True, False])
def test_restart_preserves_login_only_for_same_pinned_camera(same):
    camera = SimpleNamespace(credentials=('root', 'not-logged'), bound_host='192.168.1.10',
                             settings={'old': True}, radio_settings={'old': True},
                             _invalidate=Mock())
    view = SimpleNamespace(camera=camera, camera_profile={'fingerprint': 'saved'},
                           camera_auth=None, camera_editor=Mock(), radio_editor=Mock(),
                           camera_host=Mock(), camera_name=Mock(), camera_status=Mock(),
                           preferences={}, codec=Mock(), camera_transport_buttons={'radio': Mock()},
                           _save_preferences=Mock(), _refresh_saved_cameras=Mock(), _show_camera_info=Mock(), notify=Mock())
    profile = dict(host='192.168.1.10', ssh_fingerprint='saved' if same else 'new',
                   receiver_config={'codec': 'H.265'})
    MainWindow._radio_camera_selected(view, profile)
    if same:
        assert camera.credentials == ('root', 'not-logged')
        camera._invalidate.assert_not_called()
        view.camera_editor.load.assert_not_called()
    else:
        assert camera.credentials is None and view.camera_profile is None
        view.camera_editor.load.assert_called_once_with({})
        view.radio_editor.load.assert_called_once_with({})


def test_radio_codec_change_keeps_return_channel_available():
    view = SimpleNamespace(session=SimpleNamespace(running=True, state={}),
                           camera=Mock(), camera_editor=Mock(), notify=Mock())
    MainWindow._apply_camera_settings(view, {'video0.codec': 'h264'})
    view.camera.apply_settings.assert_called_once_with({'video0.codec': 'h264'})


@pytest.mark.parametrize('state', [{'recording': 'recording'}, {'streaming': 'streaming'}])
def test_codec_change_does_not_corrupt_active_recording_or_stream(state):
    view = SimpleNamespace(session=SimpleNamespace(running=True, state=state),
                           camera=Mock(), camera_editor=Mock(), notify=Mock())
    MainWindow._apply_camera_settings(view, {'video0.codec': 'h264'})
    view.camera.apply_settings.assert_not_called()


def test_codec_result_during_decoder_restart_updates_next_launch():
    from master.session import StationSession
    session = SimpleNamespace(running=True, decoder_restart=True,
                              selected_codec='h265', start_options={'codec': 'h265'},
                              media_options=['--codec', 'h265'])
    StationSession.restart_decoder(session, 'h264')
    assert session.selected_codec == session.start_options['codec'] == 'h264'
    assert session.media_options == ['--codec', 'h264']


def test_background_sync_skips_unsaved_edits_and_busy_commands():
    view = SimpleNamespace(camera=SimpleNamespace(busy=False, credentials=True,
        bound_host='camera', host='camera', refresh_settings=Mock(), read_radio=Mock()),
        radio_switch=None, radio_editor=SimpleNamespace(changes=lambda: {}),
        camera_editor=SimpleNamespace(changes=lambda: {}))
    MainWindow._sync_camera_settings(view)
    view.camera.read_radio.assert_called_once_with(background=True)
    MainWindow._sync_camera_settings(view)
    view.camera.refresh_settings.assert_called_once_with(background=True)
    view.camera.refresh_settings.reset_mock()
    view.camera_editor.changes = lambda: {'video0.codec': 'h264'}
    MainWindow._sync_camera_settings(view)
    view.camera.refresh_settings.assert_not_called()
    view.camera_editor.changes = lambda: {}
    view.camera.busy = True
    MainWindow._sync_camera_settings(view)
    view.camera.refresh_settings.assert_not_called()

    view.camera.busy = False
    view.radio_editor.changes = lambda: {'power': 9}
    view.camera.read_radio.reset_mock()
    MainWindow._sync_camera_settings(view)
    view.camera.read_radio.assert_not_called()
    view.camera.refresh_settings.assert_not_called()


def test_known_lan_camera_login_does_not_repeat_pairing_or_interrupt_video():
    view=SimpleNamespace(camera=SimpleNamespace(transport='lan',credentials=True),
        camera_profile={'fingerprint':'saved'},radio_camera_fingerprints={'saved'},
        _protection=lambda: {'text':'protected'},security_status=Mock(),auto_pair=Mock(),
        pairing_after_login=False,_pair_keys=Mock(),_refresh_radio=Mock(),
        module_initializer=SimpleNamespace(next_try=50))
    view.auto_pair.isChecked.return_value=True
    MainWindow._continue_lan_setup(view)
    view._pair_keys.assert_not_called()
    view._refresh_radio.assert_called_once()
    assert view.module_initializer.next_try==0
