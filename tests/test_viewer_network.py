from master.viewer_network import is_lan_address, viewer_networks, hotspot_conflicts


def interface(name, address, kind='ethernet', **options):
    return dict(name=name, addresses=[address], kind=kind, running=True, **options)


def test_hotspot_then_wifi_before_camera_cable():
    values = viewer_networks([interface('en6', '192.168.1.11'), interface('en0', '192.168.2.108', 'wifi'),
                              interface('bridge100', '192.168.3.1', '')])
    assert [v.kind for v in values] == ['hotspot', 'wifi', 'ethernet']
    assert values[0].label == 'Раздача Wi-Fi · 192.168.3.1'


def test_tunnels_and_inactive_interfaces_are_not_advertised():
    assert viewer_networks([interface('utun4', '198.18.0.1'), interface('tun0', '10.0.0.1'),
                            interface('en2', '172.16.0.2', point_to_point=True),
                            dict(name='en0', addresses=['192.168.2.10'], kind='wifi', running=False)]) == []


def test_only_rfc1918_not_python_private_benchmark_or_loopback():
    for value in ('198.18.0.1', '127.0.0.1', '169.254.1.1', '0.0.0.0', '8.8.8.8', '::1', None):
        assert not is_lan_address(value)
    for value in ('192.168.1.1', '172.31.1.1', '10.42.0.1'):
        assert is_lan_address(value)


def test_hotspot_must_not_overlap_uplink_subnet():
    values = viewer_networks([interface('en6', '192.168.2.39'), interface('bridge100', '192.168.2.1')])
    assert hotspot_conflicts(values) == ['192.168.2.1']
    values = viewer_networks([interface('en6', '192.168.2.39'), interface('bridge100', '192.168.50.1')])
    assert not hotspot_conflicts(values)


def test_reversed_dhcp_range_does_not_report_working_hotspot():
    from master.viewer_network import hotspot_pool_issue
    subnet = dict(net_address='192.168.50.0', net_mask='255.255.255.0',
                  dhcp_router=['192.168.50.1'], net_range=['192.168.50.2', '192.168.50.0'])
    assert hotspot_pool_issue('192.168.50.1', [subnet])
    subnet['net_range'][1] = '192.168.50.254'
    assert not hotspot_pool_issue('192.168.50.1', [subnet])
    subnet['net_range'][0] = '192.168.50.1'
    assert hotspot_pool_issue('192.168.50.1', [subnet])
