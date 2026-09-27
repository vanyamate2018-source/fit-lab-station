import ast
from pathlib import Path


def test_legacy_and_wfb_led_interfaces(tmp_path):
    source=Path('deployment/linux-receiver/forwarder.py').read_text()
    tree=ast.parse(source)
    module=ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('led_path','manual_led')],type_ignores=[])
    def path(*parts):
        return tmp_path.joinpath(*[str(p).lstrip('/') for p in parts])
    namespace={'Path':path}
    exec(compile(module,'led-helpers','exec'),namespace)
    old=tmp_path/'proc/net/rtl88XXau/rx1';old.mkdir(parents=True)
    (old/'led_config').touch()
    assert namespace['manual_led']('rx1') == old/'write_reg'
    assert (old/'led_config').read_text() == '0 0\n'
    new=tmp_path/'proc/net/rtl88xxau_wfb/rx2';new.mkdir(parents=True)
    (new/'led_enable').touch()
    assert namespace['manual_led']('rx2') == new/'write_reg'
    assert (new/'led_enable').read_text() == '0\n'
