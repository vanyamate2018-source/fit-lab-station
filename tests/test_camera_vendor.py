import hashlib
import subprocess
from unittest.mock import patch

import pytest
from master.camera_vendor import parse_values, update_script


def test_vendor_update_preserves_unrelated_values_comments_and_spacing(tmp_path):
    path = tmp_path / 'user.ini'
    before = '# camera\nfps = 120 ; comment\ntxpower = 20\nunknown=value\n'
    path.write_text(before)
    observed = {'values': {'fps': '120', 'txpower': '20'}, 'digest': hashlib.sha256(before.encode()).hexdigest()}
    with patch('master.camera_vendor.PATHS', (str(path),)):
        script = update_script(str(path), observed, {'fps': '60', 'txpower': '20'})
    result = subprocess.run(['sh', '-c', script], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert path.read_text() == before.replace('fps = 120', 'fps = 60')
    path.write_text('fps = 30\n')
    assert subprocess.run(['sh', '-c', script], capture_output=True).returncode != 0
    assert path.read_text() == 'fps = 30\n'


def test_ambiguous_vendor_configuration_and_unknown_target_are_rejected():
    with pytest.raises(ValueError):
        parse_values('fps=60\nfps=120')
    with pytest.raises(ValueError):
        update_script('/unrelated.ini', {'digest': '0' * 64, 'values': {}}, {'fps': '60'})


def test_public_vendor_fields_are_read_in_one_bounded_batch():
    from master.camera_vendor import read_ini
    digest = 'a' * 64
    with patch('master.camera_radio.command_sections', return_value=[
        (0, ''), (0, 'fps=60\ntxpower=40'), (0, digest + ' /etc/user.ini'),
        (1, ''), (1, ''), (1, '')]) as commands:
        assert read_ini(None) == {'/etc/user.ini': {
            'values': {'fps': '60', 'txpower': '40'}, 'digest': digest}}
    commands.assert_called_once()
    assert len(commands.call_args.args[1]) == 6
    assert not any(command.startswith('cat ') for command in commands.call_args.args[1])


def test_failed_vendor_hash_is_not_accepted_as_valid_snapshot():
    from master.camera_vendor import read_ini
    with patch('master.camera_radio.command_sections', return_value=[
        (0, ''), (0, 'fps=60'), (1, ''), (1, ''), (1, ''), (1, '')]):
        with pytest.raises(ValueError, match='контрольную сумму'):
            read_ini(None)


def test_vendor_resolution_is_case_sensitive_and_survives_file_rewrite(tmp_path):
    from master.camera_vendor import SETTING_KEYS
    path = tmp_path / 'user.ini'
    before = 'Size = 1280x720 ; resolution\nfps=60\nprivate_value=untouched\n'
    path.write_text(before)
    observed = {'values': parse_values('Size=1280x720\nfps=60'),
                'digest': hashlib.sha256(before.encode()).hexdigest()}
    changes = {SETTING_KEYS['video0.size']: '1920x1080'}
    with patch('master.camera_vendor.PATHS', (str(path),)):
        script = update_script(str(path), observed, changes)
    result = subprocess.run(['sh', '-c', script], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert path.read_text() == before.replace('1280x720', '1920x1080')
    with pytest.raises(ValueError):
        parse_values('size=1280x720')
