"""A congested master destination must not interrupt local delivery."""
import ast
import json
import socket
import threading
from pathlib import Path
from types import SimpleNamespace


def test_local_delivery_continues_when_master_send_would_block():
    source = Path(__file__).parents[1] / 'deployment/linux-receiver/forwarder.py'
    tree = ast.parse(source.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'forward_stream')
    real_socket = socket.socket
    created = []
    class Congested:
        def setblocking(self, value):
            assert value is False
        def sendto(self, *args):
            raise BlockingIOError('master unavailable')
        def close(self): pass
    def factory(*args):
        value = Congested() if len(created) == 1 else real_socket(*args)
        created.append(value)
        return value
    class Settings:
        def read_text(self): return json.dumps({'master_enabled': True, 'local_enabled': True})
    import time
    env = dict(socket=SimpleNamespace(socket=factory, AF_INET=socket.AF_INET, SOCK_DGRAM=socket.SOCK_DGRAM, SOL_SOCKET=socket.SOL_SOCKET, SO_RCVBUF=socket.SO_RCVBUF, timeout=socket.timeout),
               json=json, Path=lambda _:Settings(), time=time, stop=False, TARGET='192.0.2.1', master_targets=lambda now:['192.0.2.1'])
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
    with real_socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
        reserve.bind(('127.0.0.1',0));input_port=reserve.getsockname()[1]
    with real_socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, real_socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        receiver.bind(('127.0.0.1',0));receiver.settimeout(2)
        worker=threading.Thread(target=env['forward_stream'],args=(input_port,receiver.getsockname()[1]))
        worker.start()
        try:
            deadline=time.monotonic()+2
            while len(created)<3 and time.monotonic()<deadline:time.sleep(.01)
            for payload in (b'first',b'after-master-disconnect'):
                sender.sendto(payload,('127.0.0.1',input_port))
                assert receiver.recv(512)==payload
        finally:
            env['stop']=True;worker.join(2)
            assert not worker.is_alive()


def test_routing_follows_authenticated_peer_after_lan_to_wifi(tmp_path):
    source = Path(__file__).parents[1] / 'deployment/linux-receiver/forwarder.py'
    function = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'master_targets')
    env = dict(json=json, Path=lambda _: tmp_path, BOOT_ID='boot', TARGET='192.0.2.39')
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
    def peer(name, address, seen, boot='boot'):
        (tmp_path/name).write_text(json.dumps(dict(address=address, seen=seen, boot_id=boot, authenticated=True)))
    peer('old.json', '192.0.2.39', 10)
    peer('new.json', '192.0.2.108', 15)
    peer('previous-boot.json', '192.0.2.90', 15, 'old-boot')
    assert env['master_targets'](16) == ['192.0.2.108']
    assert env['master_targets'](20) == ['192.0.2.39']
