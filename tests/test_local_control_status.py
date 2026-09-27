import json
from master.local_control_status import LocalControlStatus
from receiver.control_service import key_revision


def test_gui_does_not_own_service_and_rejects_stale_status(tmp_path):
    control = LocalControlStatus.__new__(LocalControlStatus)
    control.path = tmp_path / 'status.json'
    control.boot = 'this-boot'
    assert control.poll(10) == {'state': 'retrying'}
    value = dict(owner='service', boot_id='this-boot', updated=10, state='connected')
    control.path.write_text(json.dumps(value))
    assert control.poll(11)['state'] == 'connected'
    control.close()
    assert control.poll(11)['state'] == 'connected'
    assert control.poll(13) == {'state': 'retrying'}
    value['owner'] = 'old-gui'
    control.path.write_text(json.dumps(value))
    assert control.poll(11) == {'state': 'retrying'}


def test_control_rekeys_when_contents_change(tmp_path):
    key = tmp_path / 'key'
    assert key_revision(key) is None
    key.write_bytes(b'a' * 64)
    first = key_revision(key)
    key.write_bytes(b'b' * 64)
    assert first != key_revision(key)
