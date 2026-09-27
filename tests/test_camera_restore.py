from copy import deepcopy
import pytest

from master.camera_restore import CameraRestoreStore, default_patch


@pytest.fixture
def settings():
    return {'schema': {'properties': {
        'video0': {'properties': {'fps': {'type': 'integer', 'enum': [30,60], 'default':30},
                                 'size': {'type':'string'}}},
        'image': {'properties': {'contrast': {'type':'integer','default':50},
                                 'secret': {'type':'string','default':'hidden'}}},
        'network': {'properties': {'ip': {'type':'string','default':'192.168.1.10'}}}}},
        'config': {'video0': {'fps':60,'size':'1280x720'},
                   'image': {'contrast':60,'secret':'hidden'},'network': {'ip':'192.168.2.47'}}}


def test_restore_is_scoped_to_verified_camera_and_excludes_secrets(tmp_path, settings):
    store=CameraRestoreStore(tmp_path,'SHA256:camera-one')
    store.initial(settings)
    assert 'hidden' not in store.path.read_text() and 'network' not in store.path.read_text()
    assert store.path.stat().st_mode & 0o777 == 0o600
    changed=deepcopy(settings);changed['config']['video0']['fps']=30
    store.initial(changed)
    assert store.patch('initial',changed)=={'video0.fps':60}
    with pytest.raises(ValueError,match='нет сохранённых'):
        CameraRestoreStore(tmp_path,'SHA256:other-camera').patch('initial',changed)


def test_undo_only_confirmed_changed_fields_and_rejects_external_edits(tmp_path,settings):
    store=CameraRestoreStore(tmp_path,'SHA256:one')
    after=deepcopy(settings);after['config']['video0']['fps']=30
    store.confirmed(settings['schema'],settings['config'],after['config'],{'video0.fps':30})
    assert store.patch('previous',after)=={'video0.fps':60}
    with pytest.raises(ValueError,match='параметры менялись'):
        store.patch('previous',settings)
    with pytest.raises(ValueError,match='не подтверждено'):
        store.confirmed(settings['schema'],settings['config'],settings['config'],{'video0.fps':30})


def test_defaults_only_current_section_and_firmware_declared_fields(settings):
    assert default_patch(settings['schema'],settings['config'],'video0')=={'video0.fps':30}
    assert default_patch(settings['schema'],settings['config'],'image')=={'image.contrast':50}
    assert default_patch(settings['schema'],settings['config'],'network')=={}
