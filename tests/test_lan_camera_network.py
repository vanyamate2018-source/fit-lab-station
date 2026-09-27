from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtNetwork import QNetworkInterface as Q
import pytest

from master.camera_lan import ethernet_hosts
from master.camera import valid_host


def test_camera_filter_excludes_generic_rtsp_and_tplink():
    from master.camera_lan import camera_devices
    devices = [dict(host='192.168.2.10', family='TP-Link · IP-камера', video_service_available=True),
               dict(host='192.168.2.11', family='RTSP-камера', video_service_available=True),
               dict(host='192.168.2.12', family='OpenIPC · веб-панель', video_service_available=False),
               dict(host='192.168.2.13', family='OpenIPC / Majestic', video_service_available=True)]
    assert [d['host'] for d in camera_devices(devices)] == ['192.168.2.12', '192.168.2.13']


def test_new_results_arrive_before_slow_device_and_scan_survives_bad_device():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from master.camera_lan import discover_hosts
    release, found = Event(), Event()
    def probe(host):
        if host == 'slow':
            release.wait(2)
            return None
        if host == 'bad':
            raise ValueError('malformed response')
        return dict(host=host, family='OpenIPC / Majestic')
    with patch('master.camera_lan.probe', side_effect=probe), ThreadPoolExecutor(1) as executor:
        future = executor.submit(discover_hosts, ['slow','camera','bad'], lambda _: found.set())
        try:
            assert found.wait(1)
            assert not future.done()
        finally:
            release.set()
        assert future.result() == [dict(host='camera', family='OpenIPC / Majestic')]


def test_two_subnets_are_not_truncated_to_first_network_and_own_ips_excluded():
    interfaces = [interface(Q.InterfaceType.Wifi,'192.168.2.108',24),
                  interface(Q.InterfaceType.Ethernet,'192.168.2.39',24),
                  interface(Q.InterfaceType.Ethernet,'192.168.1.2',24)]
    with patch('master.camera_lan.QNetworkInterface.allInterfaces',return_value=interfaces):
        hosts=ethernet_hosts()
    assert '192.168.2.254' in hosts and '192.168.1.10' in hosts
    assert not {'192.168.2.108','192.168.2.39','192.168.1.2'} & set(hosts)


def test_generic_ip_camera_never_gets_ssh_probe():
    from master.camera import discover_candidate
    result=dict(state='found',host='192.168.2.169',family='TP-Link · IP-камера',video_service_available=True)
    with patch('master.camera.discover',return_value=result), patch('master.camera.socket.create_connection') as connect:
        assert discover_candidate(result['host'],fingerprint_only_if_video=True)==result
        connect.assert_not_called()


@pytest.mark.parametrize('fingerprint,expected',['SHA256:saved SHA256:saved'.split(), 'SHA256:other missing'.split()])
def test_password_protected_known_camera_requires_matching_ssh_identity(fingerprint,expected):
    from master.camera_lan import probe, openipc_candidate
    host='192.168.2.148'
    known={host:dict(fingerprint='SHA256:saved',family='OpenIPC / Majestic')}
    candidate=dict(state='found',host=host,family='Сетевая камера',candidate_fingerprint=fingerprint,video_service_available=False)
    with patch('master.camera_lan.socket.create_connection'),patch('master.camera.discover_candidate',return_value=candidate):
        result=probe(host,known)
        assert openipc_candidate(result)==(expected!='missing')


def interface(kind,address,prefix=30,up=True):
    entry=SimpleNamespace(ip=lambda:SimpleNamespace(toString=lambda:address),prefixLength=lambda:prefix)
    return SimpleNamespace(type=lambda:kind,flags=lambda:(Q.InterfaceFlag.IsUp|Q.InterfaceFlag.IsRunning)
                           if up else Q.InterfaceFlag(0), addressEntries=lambda:[entry])


def test_switch_camera_is_discovered_over_wifi_and_ethernet_only():
    interfaces=[interface(Q.InterfaceType.Wifi,'192.168.2.1'),
                interface(Q.InterfaceType.Ethernet,'192.168.3.1'),
                interface(Q.InterfaceType.Virtual,'10.20.30.1'),
                interface(Q.InterfaceType.Ethernet,'10.40.0.1',16),
                interface(Q.InterfaceType.Wifi,'192.168.4.1',up=False)]
    with patch('master.camera_lan.QNetworkInterface.allInterfaces',return_value=interfaces):
        assert ethernet_hosts()==['192.168.2.2','192.168.3.2']


@pytest.mark.parametrize('address',['','  ','not-an-ip','192.168.1.300'])
def test_invalid_camera_address_has_user_message(address):
    with pytest.raises(ValueError,match='Укажите адрес камеры'):
        valid_host(address)


def test_empty_find_runs_discovery_without_changing_camera():
    from master.ui.main_window import MainWindow
    view=SimpleNamespace(radio_switch=None,camera_host=Mock(text=Mock(return_value='')),
        camera=SimpleNamespace(host='192.168.1.10',transport='radio'),
        camera_transport_buttons={'lan':Mock()},lan_discovery=Mock(),camera_tabs=Mock(),notify=Mock())
    MainWindow._set_camera_host(view)
    assert view.camera.host=='192.168.1.10'
    view.lan_discovery.scan_now.assert_called_once()


def test_known_camera_with_only_ssh_is_still_probed():
    from master.camera_lan import probe
    host='192.168.2.20'
    known={host:dict(fingerprint='saved',family='OpenIPC / Majestic')}
    def connect(address,timeout):
        if address[1] != 22: raise OSError('closed')
        return Mock(__enter__=Mock(),__exit__=Mock())
    result=dict(state='found',host=host,family='OpenIPC / Majestic',candidate_fingerprint='saved')
    with patch('master.camera_lan.socket.create_connection',side_effect=connect),patch('master.camera.discover_candidate',return_value=result) as discover:
        assert probe(host,known)['candidate_fingerprint']=='saved'
        assert discover.call_args.kwargs['known_identities']['saved']==known[host]


def test_protected_camera_new_ip_recognized_only_by_saved_identity():
    from master.camera import discover_candidate
    import time
    host='192.168.2.22'
    for identity,expected in [('saved','OpenIPC / Majestic'),('other','Сетевая камера')]:
        candidate=dict(state='found',host=host,family='Сетевая камера',authentication_required=True)
        with patch('master.camera.discover',return_value=candidate),patch.dict('master.camera._recent_fingerprints',{host:(time.monotonic(),identity)}):
            result=discover_candidate(host,fingerprint_only_if_video=True,known_identities={'saved':dict(family='OpenIPC / Majestic')})
            assert result['family']==expected
