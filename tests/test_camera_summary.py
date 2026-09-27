from master.camera_summary import camera_summary


def test_fresh_readback_wins_over_initial_login_and_preserves_zero():
    profile = {'values': {'fps': '60', 'codec': 'h265', 'size': '1280x720', 'gop': '1', 'osd_enabled': 'true',
                          'sensor': 'imx415', 'radio_driver': '../../bus/usb/drivers/rtl88x2eu'},
               'settings': {'config': {'video0': {'fps': 60}}}}
    values = camera_summary(profile, {'config': {'video0': {'fps': 30, 'codec': 'h264', 'size': '1920x1080',
                                                           'gopSize': '0.5', 'bitrate': 0},
                                                'osd': {'enabled': False, 'template': ''}}})
    assert values['fps'] == '30 FPS' and values['codec'] == 'H.264'
    assert values['size'] == '1920 × 1080' and values['gop'] == '0.5 с'
    assert values['bitrate'] == '0 кбит/с'
    assert values['osd_enabled'] == 'Выключено' and values['osd_template'] == '—'
    assert values['sensor'] == 'imx415' and values['radio_driver'] == 'rtl88x2eu'
    assert profile['values']['fps'] == '60'


def test_unknown_camera_does_not_report_osd_disabled_or_service_running():
    assert camera_summary(None)['osd_enabled'] == '—'
    assert camera_summary(None)['radio_service'] == '—'
    assert camera_summary({'values': {'radio_service': '/usr/bin/wifibroadcast'}})['radio_service'] == 'Установлена'
