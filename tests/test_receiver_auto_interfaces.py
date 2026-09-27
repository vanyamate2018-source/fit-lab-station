import ast
from pathlib import Path


ROOT = Path(__file__).parents[1] / 'deployment/linux-receiver'


def discovery(filename):
    tree = ast.parse((ROOT/filename).read_text())
    definitions = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in ('receiver_interfaces', 'receiver_macs'))
                   or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'RECEIVER_MACS' for t in n.targets))]
    import json
    env = {'Path': Path, 'json': json}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), filename, 'exec'), env)
    return env


def device(root, name, mac, port, product='8812'):
    usb = root.parent/'usb'/port
    usb.mkdir(parents=True, exist_ok=True)
    (usb/'idVendor').write_text('0bda')
    (usb/'idProduct').write_text(product)
    child = usb/(port+':1.0');child.mkdir(exist_ok=True)
    net = root/name;net.mkdir(parents=True)
    (net/'address').write_text(mac)
    (net/'device').symlink_to(child)
    return net


def test_port_and_name_changes_preserve_role(tmp_path):
    env=discovery('forwarder.py');root=tmp_path/'net';root.mkdir()
    macs=env['RECEIVER_MACS']
    first=device(root,'wlan7',macs[0],'1-1')
    device(root,'wlan2',macs[2],'7-1')
    assert env['receiver_interfaces'](root)==('wlan7',None,'wlan2')
    # Move RX1 to another port and rename the net interface, without changing identity.
    (first/'device').unlink();(first/'address').unlink();first.rmdir()
    device(root,'rx-main',macs[0],'5-1')
    device(root,'wlan9',macs[1],'3-1')
    assert env['receiver_interfaces'](root)==('rx-main','wlan9','wlan2')


def test_ambiguous_and_unsupported_devices_are_not_claimed(tmp_path):
    env=discovery('forwarder.py');root=tmp_path/'net';root.mkdir();macs=env['RECEIVER_MACS']
    device(root,'a',macs[0],'1-1');device(root,'b',macs[0],'2-1')
    device(root,'c',macs[1],'3-1',product='1234')
    device(root,'d','00:11:22:33:44:55','4-1')
    assert env['receiver_interfaces'](root)==(None,None,None)


def test_tx_and_rx_resolve_identical_roles():
    a=discovery('forwarder.py');b=discovery('command_bridge.py')
    assert a['RECEIVER_MACS']==b['RECEIVER_MACS']
    trees=[]
    for filename in ('forwarder.py','command_bridge.py'):
        tree=ast.parse((ROOT/filename).read_text())
        trees.append(ast.dump(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='receiver_interfaces')))
    assert trees[0]==trees[1]


def test_saved_replacement_is_used_by_both_rx_and_tx(tmp_path):
    import json
    root=tmp_path/'net';root.mkdir()
    slots=['00:11:22:33:44:00','00:11:22:33:44:01','00:11:22:33:44:02']
    saved=tmp_path/'roles.json';saved.write_text(json.dumps({'slots':slots}))
    for i,mac in enumerate(slots):device(root,'new'+str(i),mac,str(i)+'-1')
    for filename in ('forwarder.py','command_bridge.py'):
        env=discovery(filename)
        env['Path']=lambda _:saved
        assert env['receiver_macs']()==tuple(slots)
        assert env['receiver_interfaces'](root)==('new0','new1','new2')
