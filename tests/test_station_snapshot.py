import json
from master.diagnostics import station_snapshot


def test_export_includes_measurements_but_excludes_unlisted_data():
    state = {'phase': 'video', 'fps': 60, 'width': 1280, 'height': 720,
             'credentials': 'private-marker', 'camera_config': {'password': 'private-marker'},
             'control': {'state': 'connected', 'rtt_ms': 20, 'key': 'private-marker'},
             'radio': {'totals': {'lost_packets': 3, 'private': 'private-marker'}},
             'receivers': [{'index': 0, 'rssi_dbm': -50, 'private': 'private-marker'}]}
    result = station_snapshot(state, True, 2)
    assert result['video']['fps'] == 60 and result['usb_connected'] == 2
    assert result['packets']['lost_packets'] == 3
    assert result['control']['rtt_ms'] == 20
    assert 'private-marker' not in json.dumps(result)
    assert result['end_to_end_latency_ms'] is None
