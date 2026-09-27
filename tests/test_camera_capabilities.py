from unittest.mock import patch
from master.camera_capabilities import assess, summary
from master.camera_lan import probe, discover_hosts


def test_bands_and_writes_require_measured_evidence():
    values = dict(cli='/bin/cli', majestic='/bin/majestic', codec='h265', hostname='5.8G-camera')
    a = assess(values)
    assert a['bands'] == [] and a['compatibility'] == 'partial'
    assert a['capabilities'] == []
    a = assess(values, dict(channels=[1, 6, 161], restart_ready=True, adaptive=False,
                           live={'frequency_mhz': 5805}), {'config': {'system': {'unsafe': False}}})
    assert a['bands'] == ['2,4 ГГц', '5 ГГц']
    assert 'radio.power.write' not in a['capabilities']
    assert 'radio.frequency.write' in a['capabilities']
    assert summary(a)['active_frequency'] == '5805 МГц'


def test_adaptive_driver_cannot_be_overridden_by_assessment():
    a = assess(dict(cli='cli', majestic='majestic', codec='h264'),
               dict(channels=[36], restart_ready=True, adaptive=True, power_scale=.5, power_limits={36: 20}))
    assert 'radio.frequency.write' not in a['capabilities']
    assert 'radio.power.write' not in a['capabilities']


def test_lan_scan_never_substitutes_another_mdns_camera():
    with patch('master.camera_lan.socket.create_connection'), \
         patch('master.camera.discover_candidate', return_value={'state': 'offline'}) as find:
        assert probe('192.168.2.9') is None
        find.assert_called_once_with('192.168.2.9', fallback=False, fingerprint_only_if_video=True)


def test_unreachable_network_has_no_devices():
    with patch('master.camera_lan.socket.create_connection', side_effect=OSError):
        assert discover_hosts(['192.168.2.9', '192.168.2.10']) == []
