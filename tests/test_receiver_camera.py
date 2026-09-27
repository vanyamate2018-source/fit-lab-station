import json
from types import SimpleNamespace
import pytest
from master.receiver_camera import select_receiver_camera
from shared.pairing_store import PairingStore


def test_receiver_camera_is_verified_and_selected_without_retuning(tmp_path, monkeypatch):
    store = PairingStore(tmp_path/'data')
    (store.root/'logs').mkdir(parents=True)
    saved=[]
    for identity in ('a'*24,'b'*24):
        p=store.create(identity,'camera','fp-'+identity)
        p['receiver_config']={'radio_channel':36,'radio_width':20}
        store.activate(p);store.finish(p,True);saved.append(p)
    store.select_known(saved[0]['identity'])
    remote=dict(saved[1])
    monkeypatch.setattr('master.receiver_camera.subprocess.run',lambda *a,**kw: SimpleNamespace(returncode=0,stdout=json.dumps(remote).encode()))
    assert select_receiver_camera(tmp_path,'192.168.2.36')['identity']==saved[1]['identity']
    assert store.active_key.read_bytes()==store.key_for(saved[1]).read_bytes()
    remote['gs_public']='mismatch'
    with pytest.raises(ValueError): select_receiver_camera(tmp_path,'192.168.2.36')
