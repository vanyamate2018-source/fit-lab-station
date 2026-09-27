import pytest
from shared.radio_settings import available_channels, diagnose, frequency, live_interface, receiver_settings
from shared.camera_settings import needs_reload
from master.web_stream_worker import relay_config


def test_channels_are_filtered_by_camera_limits_and_local_receiver():
    text = """* 5805 MHz [161] (20.0 dBm)
    * 5180 MHz [36] (20.0 dBm) (no IR)
    * 5260 MHz [52] (20.0 dBm) (radar detection)
    * 5825 MHz [165] (disabled)
    * 5885 MHz [177] (20.0 dBm)
    * 5805 MHz [149] (20.0 dBm)
    """
    assert available_channels(text) == [161]
    assert frequency(161) == 5805
    assert frequency(14) == 2484
    for channel in (True, 177, "161"):
        with pytest.raises(ValueError):
            receiver_settings(channel)


def test_frequency_picker_is_locked_to_observed_radio_band():
    from shared.radio_settings import same_band_channels
    reported = [1, 6, 11, 14, 36, 149, 161]
    assert same_band_channels(reported, {'frequency_mhz': 5180}) == [36, 149, 161]
    assert same_band_channels(reported, {'frequency_mhz': 2437}) == [1, 6, 11]
    assert same_band_channels(reported, {}) == []
    assert same_band_channels(reported, {'frequency_mhz': 6000}) == []


def test_saved_channel_is_not_reported_as_effective():
    live = live_interface("Interface wlan0\n channel 161 (5805 MHz), width: 20 MHz, center1: 5805 MHz\n txpower 20.00 dBm")
    assert live == {"channel": 161, "frequency_mhz": 5805, "width": 20, "driver_dbm": 20.0}
    messages = diagnose({"channel": 149, "width": 40}, live, True, "yaml")
    assert len(messages) == 3
    assert "работает 161" in messages[0]
    assert "ALink" in messages[-1]
    assert not live_interface("iw: not found")


@pytest.mark.parametrize("extra,reload", [({}, True), ({"x-live": True}, False),
    ({"x-reload": "live"}, False), ({"x-reload": "none"}, False),
    ({"x-reload": "service:osd"}, False), ({"x-reload": "channel:0"}, False),
    ({"x-reload": "service:"}, True), ({"x-reload": "new-class"}, True)])
def test_video_runtime_apply_uses_firmware_reload_metadata(extra, reload):
    schema = {"properties": {"video0": {"properties": {"fps": {"type": "integer", **extra}}}}}
    assert needs_reload(schema, {"video0": {"fps": 60}}, {"video0.fps": 30}) is reload


def test_web_relay_is_lan_only_and_viewers_cannot_publish():
    config = relay_config("192.168.1.20", 22221, 22222)
    assert config["rtspAddress"].startswith("127.0.0.1:")
    assert config["apiAddress"].startswith("127.0.0.1:")
    assert config["webrtcICEServers2"] == []
    assert config["authInternalUsers"][1]["permissions"] == [{"action": "read", "path": "live"}]
    assert not any(config[key] for key in ("hls", "rtmp", "srt", "moq", "playback"))


def test_power_mapping_requires_driver_confirmation_and_obeys_camera_limits():
    from shared.radio_settings import power_value, channel_power_limits
    caps = '* 5805 MHz [161] (20.0 dBm)\n* 5260 MHz [52] (20.0 dBm) (radar detection)'
    device = {"power_scale": .5, "power_limits": channel_power_limits(caps)}
    assert power_value(9.5, device, 161) == 19
    for value in (-1, 20.5, 9.2, True, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            power_value(value, device, 161)
    with pytest.raises(ValueError):
        power_value(10, device, 52)


def test_runcam_manufacturer_reference_does_not_change_driver_scale():
    from shared.radio_settings import runcam_power_reference, power_value
    snapshot = dict(vendor_managed=True, driver='rtl88x2eu', config={'power': 40},
                    power_scale=.5, power_limits={165: 20})
    assert runcam_power_reference(snapshot)['mw'] == 400
    assert runcam_power_reference(snapshot)['dbm'] == 26
    assert power_value(20, snapshot, 165) == 40
    assert runcam_power_reference({**snapshot, 'vendor_managed': False}) is None
    assert runcam_power_reference({**snapshot, 'config': {'power': 41}}) is None
