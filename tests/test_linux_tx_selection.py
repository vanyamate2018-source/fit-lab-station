import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('linux_bridge', Path(__file__).parents[1]/'deployment/linux-receiver/command_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_select_stronger_without_flapping_and_fail_over():
    s=bridge.TxSelector()
    assert s.select([0,1],{0:-45,1:-30},100)==1
    assert s.select([0,1],{0:-28,1:-30},105)==1
    assert s.select([0,1],{0:-20,1:-30},111)==1
    assert s.select([0,1],{0:-20,1:-30},114)==0
    assert s.select([1],{},114.1)==1
    assert s.select([],{},115) is None


def test_stale_missing_statistics_keep_owner():
    s=bridge.TxSelector()
    assert s.select([1],{},100)==1
    assert s.select([0,1],{},120)==1


def test_control_rssi_slot_and_freshness(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'CONTROL_LOGS',tmp_path)
    (tmp_path/'lan-control').mkdir()
    (tmp_path/'lan-control/control-rx.log').write_text('99000\tRX_ANT\t5720:1:20\t7f00000100000100\t5:-30:-28:-26:0:0:0\n90000\tRX_ANT\t5720:1:20\t7f00000100000000\t5:-20:-18:-16:0:0:0\n')
    assert bridge.control_signals(100)=={1:-28}
    assert bridge.control_signals(105)=={}


def test_packet_delivery_outweighs_strong_rssi():
    s=bridge.TxSelector()
    assert s.select([0,1],{0:-30,1:-45},100,{0:10,1:10})==0
    assert s.select([0,1],{0:-30,1:-45},111,{0:2,1:10})==0
    assert s.select([0,1],{0:-30,1:-45},114,{0:2,1:10})==1
    assert s.select([0,1],{0:-30,1:-45},115,{0:10,1:10})==1


def test_metrics_do_not_keep_old_rssi_or_double_count_antennas(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'CONTROL_LOGS',tmp_path)
    (tmp_path/'lan-control').mkdir()
    (tmp_path/'lan-control/control-rx.log').write_text(
        '98000 RX_ANT 5200:1:20 7f00000100000000 50:-20:-18:-16:0:0:0\n'
        '99000 RX_ANT 5200:1:20 7f00000100000000 5:-40:-38:-36:0:0:0\n'
        '99000 RX_ANT 5200:1:20 7f00000100000001 5:-42:-40:-38:0:0:0\n')
    assert bridge.control_metrics(100)==({0:-38},{0:5})


def test_reappearing_usb_must_be_monitor_and_up(tmp_path):
    p=tmp_path/'rx1';p.mkdir()
    (p/'type').write_text('1')
    (p/'flags').write_text('0x1003')
    assert not bridge.interface_ready('rx1',tmp_path)
    (p/'type').write_text('803')
    (p/'flags').write_text('0x1002')
    assert not bridge.interface_ready('rx1',tmp_path)
    (p/'flags').write_text('0x1003')
    assert bridge.interface_ready('rx1',tmp_path)
    (p/'flags').unlink()
    assert not bridge.interface_ready('rx1',tmp_path)
