import json
from shared.master_presence import connected_masters,PresenceNotice

def test_requires_fresh_authenticated_lease(tmp_path):
    file=tmp_path/'1.json'
    file.write_text(json.dumps(dict(address='192.168.2.39',seen=100,authenticated=True,boot_id='boot')))
    assert connected_masters(tmp_path,103,boot='boot')==['192.168.2.39']
    assert connected_masters(tmp_path,103.5,boot='boot')==[]
    assert connected_masters(tmp_path,99,boot='boot')==[]
    assert connected_masters(tmp_path,103,boot='new-boot')==[]
    file.write_text(json.dumps(dict(address='192.168.2.39',seen=100,authenticated=False,boot_id='boot')))
    assert connected_masters(tmp_path,103,boot='boot')==[]


def test_old_lease_without_boot_cannot_reappear_after_reboot(tmp_path):
    (tmp_path/'old.json').write_text(json.dumps(dict(address='192.168.2.39', seen=1, authenticated=True)))
    assert connected_masters(tmp_path,2,boot='new') == []


def test_presence_does_not_wait_for_camera_credentials(monkeypatch,tmp_path):
    import io
    from master import lan_presence, binding_sync
    def forbidden(*args, **kwargs):
        raise AssertionError('Presence must not access camera bindings or vault')
    monkeypatch.setattr(binding_sync, 'sync_bindings', forbidden)
    monkeypatch.setattr(lan_presence.threading.Thread, 'start', lambda self: None)
    presence=lan_presence.LanPresence(tmp_path,'192.0.2.1')
    class Child:
        returncode=None
        stdin=io.BytesIO()
        def poll(self): return self.returncode
        def terminate(self): self.returncode=0
        def wait(self,*args): return self.returncode
    child=Child()
    seen=[]
    def popen(*args,**kwargs):
        seen.append(args[0]);return child
    def wait(delay):
        if not presence.closed.is_set():
            assert child.stdin.getvalue()==b'P\n'
        presence.closed.set()
        return True
    monkeypatch.setattr(lan_presence.subprocess,'Popen',popen)
    monkeypatch.setattr(presence.closed,'wait',wait)
    presence.run()
    assert len(seen)==1


def test_window_starts_presence_before_sync_without_video(monkeypatch,tmp_path):
    import ast
    import os
    from pathlib import Path
    from types import SimpleNamespace
    import pytest
    from master import lan_presence
    started=[]
    monkeypatch.setattr(lan_presence,'LanPresence',lambda root,host: started.append((root,host)) or object())
    monkeypatch.setenv('FIT_LAB_RECEIVER_HOST','192.0.2.1')
    class SyncReached(Exception): pass
    def tick(): raise SyncReached()
    window=SimpleNamespace(embedded_receiver=False,config=SimpleNamespace(data_root=tmp_path/'data'),
                           session=SimpleNamespace(running=False),module_initializer=SimpleNamespace(tick=tick))
    # Exercise the real handler without constructing a native window or starting radio.
    tree=ast.parse((Path(__file__).parents[1]/'master/ui/main_window.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_update_modules')
    namespace={'os':os}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'<presence-handler>','exec'),namespace)
    with pytest.raises(SyncReached): namespace['_update_modules'](window)
    with pytest.raises(SyncReached): namespace['_update_modules'](window)
    assert started==[(tmp_path,'192.0.2.1')]

def test_no_initial_false_alarm_or_repeated_outage():
    state=PresenceNotice()
    assert state.update(False) is None
    assert state.update(True) is None
    assert state.update(False)=='lost'
    assert state.update(False) is None
    assert state.update(True)=='restored'
    assert state.update(True) is None
