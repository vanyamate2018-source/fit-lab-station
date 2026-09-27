import json
from pathlib import Path

import pytest
from receiver.usb_registry import ReceiverRegistry, DEFAULT_MACS, supported_radios
from test_receiver_auto_interfaces import device


def radio(root, name, mac, port, driver='rtl88xxau_wfb'):
    net = device(root, name, mac, port)
    drivers = root.parent/'drivers'/driver
    drivers.mkdir(parents=True, exist_ok=True)
    ((net/'device').resolve()/'driver').symlink_to(drivers)
    return net


def test_adopts_replacement_and_persists_without_moving_live_roles(tmp_path):
    root=tmp_path/'net';root.mkdir()
    registry=ReceiverRegistry(tmp_path/'roles.json',root)
    radio(root,'rx-one',DEFAULT_MACS[0],'1-1')
    radio(root,'rx-three',DEFAULT_MACS[2],'2-1')
    replacement='00:11:22:33:44:55'
    radio(root,'arbitrary-name',replacement,'5-1')
    assert registry.poll(100)==[]
    assert registry.poll(107)==[]
    assert registry.poll(108)==[dict(index=1,mac=replacement,interface='arbitrary-name')]
    assert registry.slots==[DEFAULT_MACS[0],replacement,DEFAULT_MACS[2]]
    assert ReceiverRegistry(registry.path,root).slots==registry.slots
    assert registry.poll(200)==[]


def test_fourth_and_unsupported_do_not_evict_receivers(tmp_path):
    root=tmp_path/'net';root.mkdir()
    for i,mac in enumerate(DEFAULT_MACS):radio(root,'rx'+str(i),mac,str(i)+'-1')
    radio(root,'extra','00:11:22:33:44:55','5-1')
    radio(root,'wrong-driver','00:11:22:33:44:66','6-1','unrelated')
    registry=ReceiverRegistry(tmp_path/'roles.json',root)
    assert registry.poll(0)==registry.poll(100)==[]
    assert registry.slots==list(DEFAULT_MACS)
    assert '00:11:22:33:44:66' not in supported_radios(root)


def test_failed_save_retries_and_corrupt_file_recovers(tmp_path,monkeypatch):
    root=tmp_path/'net';root.mkdir();path=tmp_path/'roles.json'
    path.write_text('{invalid')
    registry=ReceiverRegistry(path,root)
    import receiver.usb_registry as module
    original=module.atomic_write
    def fail(*a,**kw):raise OSError('disk temporarily unavailable')
    monkeypatch.setattr(module,'atomic_write',fail)
    with pytest.raises(OSError):registry.poll(100)
    assert registry.dirty
    monkeypatch.setattr(module,'atomic_write',original)
    registry.poll(101)
    assert json.loads(path.read_text())['slots']==list(DEFAULT_MACS)
    assert not registry.dirty


def test_only_free_roles_assigned_when_all_radios_are_new(tmp_path):
    root=tmp_path/'net';root.mkdir()
    for i in range(3):radio(root,'rx'+str(i),'00:11:22:33:44:%02x'%i,str(i)+'-1')
    registry=ReceiverRegistry(tmp_path/'roles.json',root)
    registry.poll(0)
    changes=registry.poll(8)
    assert [c['index'] for c in changes]==[0,1,2]
    assert len(set(registry.slots))==3
