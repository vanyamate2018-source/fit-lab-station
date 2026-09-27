import copy
import pytest
from shared.camera_settings import fields, make_patch, apply_checked

SCHEMA = {"properties": {"video0": {"properties": {
    "fps": {"type": "integer", "minimum": 1, "maximum": 120},
    "codec": {"type": "string", "enum": ["h264", "h265"]},
    "password": {"type": "string"}, "missing": {"type": "boolean"},
    "size": {"type": "string", "readOnly": True}}},
    "network": {"properties": {"enabled": {"type": "boolean"}}}}}
BASE = {"video0": {"fps": 120, "codec": "h265", "password": "not-for-export", "size": "1280x720"},
        "network": {"enabled": True}}


def test_discovery_excludes_secrets_unknown_values_and_unmanaged_network():
    assert set(fields(SCHEMA, BASE)) == {"video0.fps", "video0.codec", "video0.size"}
    for path in ("video0.missing", "video0.password", "network.enabled", "video0.size"):
        with pytest.raises(ValueError):
            make_patch(SCHEMA, BASE, {path: True})


@pytest.mark.parametrize("value", [0, 121, True, "60", 60.5])
def test_device_limits_and_types(value):
    with pytest.raises(ValueError):
        make_patch(SCHEMA, BASE, {"video0.fps": value})


def test_only_changed_values_are_written():
    assert make_patch(SCHEMA, BASE, {"video0.fps": 60, "video0.codec": "h265"}) == {"video0.fps": 60}


def test_firmware_unset_defaults_are_not_validated_or_written():
    config = copy.deepcopy(BASE)
    config["video0"]["fps"] = None
    assert make_patch(SCHEMA, config, {"video0.fps": None, "video0.codec": "h264"}) == {"video0.codec": "h264"}


def test_lost_readback_is_reported_as_uncertain():
    api = FakeAPI()
    def uncertain(method, path, data=None):
        if method == "GET" and api.writes:
            raise OSError("offline")
        return api(method, path, data)
    with pytest.raises(ValueError, match="могли сохраниться"):
        apply_checked(uncertain, SCHEMA, BASE, {"video0.fps": 60}, lambda _: None)


class FakeAPI:
    def __init__(self, mode="ok"):
        self.config = copy.deepcopy(BASE)
        self.writes = []
        self.mode = mode

    def __call__(self, method, path, data=None):
        if method == "POST":
            self.writes.append(data)
            for key, value in data["video0"].items():
                if self.mode != "partial" or key == "fps":
                    self.config["video0"][key] = value
            if self.mode == "timeout":
                raise OSError("timeout after save")
        return copy.deepcopy(self.config)


def test_readback_after_timeout_no_blind_retransmit():
    api, backups = FakeAPI("timeout"), []
    assert apply_checked(api, SCHEMA, BASE, {"video0.fps": 60}, backups.append)["video0"]["fps"] == 60
    assert api.writes == [{"video0": {"fps": 60}}]
    assert backups == [{"video0": {"fps": 120}}]


def test_external_modification_prevents_write():
    api = FakeAPI()
    api.config["video0"]["fps"] = 30
    with pytest.raises(ValueError, match="изменились"):
        apply_checked(api, SCHEMA, BASE, {"video0.fps": 60}, lambda _: None)
    assert not api.writes


def test_partial_write_restores_only_our_changes():
    api = FakeAPI("partial")
    with pytest.raises(ValueError, match="не полностью"):
        apply_checked(api, SCHEMA, BASE, {"video0.fps": 60, "video0.codec": "h264"}, lambda _: None)
    assert api.config == BASE
    assert api.writes[-1] == {"video0": {"fps": 120}}


def test_wire_format_matches_openipc_webui_without_changing_typed_baseline():
    from shared.camera_settings import wire_values
    values = {"video0": {"fps": 120, "codec": "h265"}, "osd": {"enabled": False}}
    assert wire_values(values) == {"video0": {"fps": "120", "codec": "h265"}, "osd": {"enabled": "false"}}
    assert type(values["video0"]["fps"]) is int
    assert values["osd"]["enabled"] is False
