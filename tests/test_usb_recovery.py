import ast
from pathlib import Path
import subprocess
import threading


def recovery():
    tree=ast.parse(Path('deployment/linux-receiver/forwarder.py').read_text())
    definitions=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in (
        'usb_identity','empty_usb_controller','UsbRecovery')]
    env=dict(Path=Path,threading=threading,subprocess=subprocess,
             receiver_macs=lambda:('mac1','mac2','mac3'), receiver_interfaces=lambda:('rx1','rx2','rx3'))
    exec(compile(ast.Module(body=definitions,type_ignores=[]),'recovery','exec'),env)
    return env


def test_controller_with_any_child_or_other_root_device_is_never_reset(tmp_path):
    env=recovery();controller=tmp_path/'host'
    one=controller/'usb1';two=controller/'usb2'
    for root in (one,two):root.mkdir(parents=True);(root/'idVendor').write_text('1d6b')
    assert env['empty_usb_controller'](controller)
    disk=two/'2-1';disk.mkdir();(disk/'idVendor').write_text('1234')
    assert not env['empty_usb_controller'](controller)
    assert not env['empty_usb_controller'](tmp_path/'missing')


def test_recovery_is_delayed_scoped_and_single_attempt(tmp_path,monkeypatch):
    env=recovery();r=env['UsbRecovery']();calls=[]
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:calls.append((a,k)))
    r.failed(0,100);r.failed(0,200)
    assert calls==[]  # Never reset a device which has not been observed.
    usb=tmp_path/'usb';usb.mkdir()
    identity=dict(mac='mac1',usb=usb,controller=tmp_path,driver=tmp_path/'driver')
    env['usb_identity']=lambda *a:identity
    r.devices[0]=identity;r.failed_since.clear()
    r.failed(0,201);r.failed(0,210)
    assert calls==[]
    r.failed(0,211);r.failed(0,500)
    assert len(calls)==1
    assert calls[0][0][0][-3:]==[str(usb),'rx1','mac1']
    r.healthy(0);r.failed(0,501);r.failed(0,511)
    assert len(calls)==2


def test_replaced_identity_and_shared_bus_are_not_reset(tmp_path,monkeypatch):
    env=recovery();r=env['UsbRecovery']();calls=[]
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:calls.append(a))
    r.devices[0]=dict(mac='old',usb=tmp_path/'missing',controller=tmp_path,driver=tmp_path/'xhci-hcd')
    r.failed(0,100);r.failed(0,120)
    assert not calls
