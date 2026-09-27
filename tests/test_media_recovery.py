from master.media_recovery import recovery_reason, decoder_stalled


def test_receiver_change_does_not_restart_live_picture():
    assert recovery_reason(100, 99.8, 100, 99.9, 1, True) is None


def test_transport_resumption_clears_old_decoder_even_same_ssrc():
    assert recovery_reason(100, 94, 99.9, 94, 1) == 'transport_resumed'
    # Only the first packet batch after the gap triggers it.
    assert recovery_reason(100.1, 99.9, 100.1, 94, 100) is None


def test_short_rf_gap_does_not_reset_decoder():
    assert recovery_reason(100, 99, 100, 99, 1) is None


def test_source_restart_requires_stale_picture():
    assert recovery_reason(100, 99.9, 100, 99, 1, True) == 'source_restarted'


def test_stall_watchdog_does_not_spin_without_packets():
    assert not decoder_stalled(100, 90, 90, 1)
    assert not decoder_stalled(100, 100, 99.8, 1)
    assert not decoder_stalled(100, 100, 0, 96)
    assert decoder_stalled(100, 100, 96, 90)
    assert decoder_stalled(100, 100, 0, 90)


def test_lan_outage_does_not_start_camera_search(tmp_path):
    from types import SimpleNamespace
    from master.session import StationSession
    calls = []
    session = SimpleNamespace(running=True, handover=None, mode='lan', state={},
        camera_search=SimpleNamespace(active='known', next=lambda *a, **kw: calls.append('search')),
        seen_cameras={'other': 10}, root=tmp_path)
    StationSession._search_camera(session, 100)
    assert calls == []
