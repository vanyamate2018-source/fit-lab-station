from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QProcess
from master.session import StationSession


def receiver(cameras):
    return SimpleNamespace(pending_start=None, handover=None, state={}, discovered=cameras,
        scanner=Mock(state=Mock(return_value=QProcess.ProcessState.Running)),
        discover_cameras=Mock(), changed=Mock(), message=Mock(), cameraChoiceRequired=Mock(), start=Mock())


@pytest.mark.parametrize('count', [0, 1, 2])
def test_start_waits_for_discovery_then_uses_only_fresh_camera(count):
    cameras = [dict(identity=str(i), last_seen=102, tuning=dict(channel=36+i*4,width=20)) for i in range(count)]
    cameras.append(dict(identity='old', last_seen=1))
    s = receiver(cameras)
    callbacks = []
    options = dict(auto_select=True, profile_identity=None)
    with patch('master.session.time.monotonic', return_value=100) as clock, \
         patch('master.session.QTimer.singleShot', side_effect=lambda _, f: callbacks.append(f)):
        StationSession._resolve_auto_start(s, options)
        callbacks.pop(0)()
        s.start.assert_not_called()
        clock.return_value = 102
        callbacks.pop(0)()
        if count == 0:
            s.start.assert_not_called()
            clock.return_value = 113
            callbacks.pop(0)()
            s.start.assert_called_once_with(auto_select=False, profile_identity=None)
        elif count == 1:
            s.start.assert_called_once_with(auto_select=False, profile_identity='0', profile_tuning=dict(channel=36,width=20))
        else:
            s.start.assert_not_called()
            s.cameraChoiceRequired.emit.assert_called_once()
        assert s.pending_start is None


def test_stop_cancels_deferred_auto_start():
    s = receiver([dict(identity='a', last_seen=1)])
    callbacks = []
    with patch('master.session.QTimer.singleShot', side_effect=lambda _, f: callbacks.append(f)):
        StationSession._resolve_auto_start(s, {})
        s.pending_start = None
        callbacks.pop(0)()
    s.start.assert_not_called()


def test_manual_current_camera_does_not_restart_video():
    s = SimpleNamespace(running=True, handover=None, search_blocked=False, state={},
                        selection_pinned=False, camera_search=SimpleNamespace(active='a'), _handover_camera=Mock())
    assert StationSession.select_camera(s, dict(identity='a', receiver_config={'radio_channel':36,'radio_width':20}))
    assert s.selection_pinned
    s._handover_camera.assert_not_called()
