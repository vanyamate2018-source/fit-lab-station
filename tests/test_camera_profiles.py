import json
import pytest

from shared.camera_profiles import load_profiles, resolve_profile


def test_profile_for_new_model_without_application_changes(tmp_path):
    profile = {"schema": 1, "id": "bench-camera", "label": "Bench camera", "driver": "openipc_ssh",
               "match": {"family": "openipc", "model": "example-model"},
               "capabilities": ["video.parameters.read", "video.parameters.write"]}
    (tmp_path / "camera.json").write_text(json.dumps(profile))
    found = resolve_profile(load_profiles(tmp_path), {"family": "openipc", "model": "example-model"},
                            ["video.parameters.read"])
    assert found["id"] == "bench-camera"
    assert found["capabilities"] == ["video.parameters.read"]


def test_unknown_camera_does_not_inherit_configuration_access(tmp_path):
    assert resolve_profile(load_profiles(tmp_path), {"family": "unknown"}, ["anything"])["driver"] is None


def test_profiles_cannot_inject_shell_commands(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps({"schema": 1, "command": "reboot"}))
    with pytest.raises(ValueError):
        load_profiles(tmp_path)


def test_transmitter_driver_does_not_match_another_radio_board(tmp_path):
    profile = {'schema': 1, 'id':'camera-eu', 'label':'Test EU camera', 'driver':'openipc_ssh',
               'match':{'family':'openipc', 'soc':'ssc338q', 'sensor':'imx415', 'radio_driver':'rtl88x2eu'}}
    (tmp_path/'eu.json').write_text(json.dumps(profile))
    observed = {'family':'openipc', 'soc':'ssc338q', 'sensor':'imx415', 'radio_driver':'rtl8812au'}
    profiles = load_profiles(tmp_path)
    assert resolve_profile(profiles, observed, [])['id'] == 'openipc'
    observed['radio_driver'] = 'rtl88x2eu'
    assert resolve_profile(profiles, observed, [])['id'] == 'camera-eu'
