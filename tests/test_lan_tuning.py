import importlib.util
import json
from pathlib import Path
import pytest


def bridge():
    path=Path(__file__).resolve().parents[1]/'deployment/linux-receiver/command_bridge.py'
    spec=importlib.util.spec_from_file_location('lan_command_bridge',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_invalid_tuning_preserves_working_configuration(tmp_path):
    module=bridge();module.SETTINGS=tmp_path/'radio-settings.json'
    module.SETTINGS.write_text('{"channel":40,"width":20}')
    for channel,width in [(0,20),(999,20),(44,80)]:
        with pytest.raises(ValueError):module.save_tuning(channel,width)
    assert json.loads(module.SETTINGS.read_text())=={'channel':40,'width':20}


def test_valid_tuning_is_atomic_and_leaves_no_temporary_files(tmp_path):
    module=bridge();module.SETTINGS=tmp_path/'radio-settings.json'
    module.save_tuning(44,20)
    assert json.loads(module.SETTINGS.read_text())=={'channel':44,'width':20}
    assert list(tmp_path.iterdir())==[module.SETTINGS]
