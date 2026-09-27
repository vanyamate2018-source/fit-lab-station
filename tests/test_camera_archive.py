import fcntl

import pytest

from shared.pairing_store import PairingStore


def paired(store, identity):
    profile = store.create(identity, '192.168.1.10', 'pin-' + identity)
    profile['receiver_config'] = dict(radio_channel=36, radio_width=20, codec='H.265')
    store.activate(profile)
    store.finish(profile, True)
    return profile


@pytest.fixture
def store(tmp_path):
    value = PairingStore(tmp_path / 'data')
    (value.root / 'logs').mkdir(parents=True)
    return value


def test_deleted_camera_leaves_discovery_and_can_be_restored_with_same_keys(store):
    profile = paired(store, 'a' * 24)
    key = store.key_for(profile).read_bytes()
    store.set_archived(profile['identity'])
    assert store.profiles() == []
    assert store.profiles(include_archived=True)[0]['archived']
    with pytest.raises(ValueError, match='удалена'):
        store.guard()
    with pytest.raises(ValueError, match='удалена'):
        store.select_known(profile['identity'])
    assert store.key_for(profile).read_bytes() == key
    store.set_archived(profile['identity'], False)
    store.guard()
    assert store.profiles()[0]['identity'] == profile['identity']
    assert store.key_for(profile).read_bytes() == key


def test_deleting_active_camera_selects_remaining_profile(store):
    one = paired(store, 'a' * 24)
    two = paired(store, 'b' * 24)
    store.set_archived(two['identity'])
    store.guard()
    assert store.read(store.active_path)['identity'] == one['identity']
    assert store.active_key.read_bytes() == store.key_for(one).read_bytes()
    assert [p['identity'] for p in store.profiles()] == [one['identity']]


def test_active_receiver_lock_prevents_removing_camera(store):
    profile = paired(store, 'a' * 24)
    with (store.root / 'logs/.fit-lab-radio-prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            store.set_archived(profile['identity'])
    assert not store.profiles()[0].get('archived')


def test_lost_camera_cannot_be_restored_or_selected_with_old_keys(store):
    profile = paired(store, 'a' * 24)
    store.set_archived(profile['identity'], revoke=True)
    assert not store.profiles()
    assert store.profiles(include_archived=True)[0]['revoked']
    with pytest.raises(ValueError, match='Доверие отозвано'):
        store.set_archived(profile['identity'], False)
    with pytest.raises(ValueError):
        store.select_known(profile['identity'])
    replacement = store.create(profile['identity'], profile['host'], profile['ssh_fingerprint'])
    replacement['receiver_config'] = profile['receiver_config']
    assert store.key_for(replacement).read_bytes() != store.key_for(profile).read_bytes()
    store.activate(replacement)
    store.finish(replacement, True)
    assert not store.profiles()[0].get('revoked')
    store.guard()


def test_legacy_identity_is_preserved_only_with_matching_pinned_key(store):
    import hashlib
    from shared.pairing_store import atomic_write
    import json
    key = b'example-public-host-key'
    identity = hashlib.sha256(key).hexdigest()[:24]
    profile = paired(store, identity)
    profile['legacy_import'] = True
    atomic_write(store.config / 'bindings' / (identity + '.json'), json.dumps(profile).encode())
    mac = '00:11:22:33:44:55'
    assert store.camera_identity(key, profile['ssh_fingerprint'], mac) == identity
    assert store.camera_identity(key, 'different-pin', mac) != identity
    profile.pop('legacy_import')
    profile['ethernet_mac'] = mac
    atomic_write(store.config / 'bindings' / (identity + '.json'), json.dumps(profile).encode())
    assert store.camera_identity(key, profile['ssh_fingerprint'], mac) == identity
    assert store.camera_identity(key, profile['ssh_fingerprint'], '00:11:22:33:44:66') != identity
