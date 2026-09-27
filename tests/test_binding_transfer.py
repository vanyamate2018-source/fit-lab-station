import json
import pytest
from shared.pairing_store import PairingStore
from shared.binding_transfer import export_bindings, import_bindings


def test_transfer_private_receiver_key_only_and_preserve_local_profile(tmp_path):
    source = PairingStore(tmp_path/'master/data')
    p = source.create('a'*24, 'camera', 'fingerprint')
    p['receiver_config'] = {'radio_channel':36,'radio_width':20}
    source.activate(p)
    source.finish(p, True)
    target = PairingStore(tmp_path/'receiver/data')
    payload = export_bindings(source.root)
    assert import_bindings(target.root, payload) == 1
    assert target.key_for(target.profiles()[0]).read_bytes() == source.key_for(p).read_bytes()
    assert not (target.folder(p['ticket'])/'drone.key').exists()
    assert target.key_for(p).stat().st_mode & 0o777 == 0o600
    assert not target.active_path.exists()
    assert import_bindings(target.root, payload) == 0
    broken = json.loads(payload)
    broken['profiles'][0]['profile']['gs_public'] = 'wrong'
    with pytest.raises(ValueError):
        import_bindings(target.root, json.dumps(broken))


def test_credentials_saved_with_readback_on_existing_profile(tmp_path):
    class Vault:
        def __init__(self): self.values = {}
        def _read(self, account): return self.values.get(account)
        def durable_write(self, account, value): self.values[account] = tuple(value)
    source = PairingStore(tmp_path/'master/data')
    p = source.create('a'*24, 'camera', 'fingerprint')
    p['receiver_config'] = {'radio_channel':36,'radio_width':20}
    source.activate(p)
    source.finish(p, True)
    sender, receiver = Vault(), Vault()
    sender.values['camera:fingerprint'] = ('root', 'test-only')
    target = tmp_path/'receiver/data'
    import_bindings(target, export_bindings(source.root))
    assert import_bindings(target, export_bindings(source.root, sender), receiver) == 0
    assert receiver.values['camera:fingerprint'] == ('root', 'test-only')
    assert 'test-only' not in (target/'config/bindings'/('a'*24+'.json')).read_text()
    receiver.values['camera:fingerprint'] = ('root', 'newer-test-only')
    with pytest.raises(ValueError):
        import_bindings(target, export_bindings(source.root, sender), receiver)
    assert receiver.values['camera:fingerprint'] == ('root', 'newer-test-only')
