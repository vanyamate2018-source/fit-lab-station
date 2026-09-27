"""Choose a reachable spectator LAN, never a VPN or the camera cable first."""
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network

LAN_RANGES = tuple(IPv4Network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def is_lan_address(value):
    try:
        address = IPv4Address(value)
        return any(address in network for network in LAN_RANGES)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class ViewerNetwork:
    name: str
    address: str
    kind: str
    prefix: int = 24

    @property
    def label(self):
        return f"{dict(hotspot='Раздача Wi-Fi', wifi='Wi-Fi', ethernet='Кабель')[self.kind]} · {self.address}"


def viewer_networks(interfaces):
    result = {}
    for interface in interfaces:
        name = interface['name']
        if not interface.get('running') or interface.get('point_to_point'):
            continue
        if name.lower().startswith(('utun', 'tun', 'tap', 'wg', 'ppp', 'ipsec', 'tailscale')):
            continue
        kind = 'hotspot' if name == 'bridge100' else interface.get('kind')
        if kind not in ('hotspot', 'wifi', 'ethernet'):
            continue
        for entry in interface.get('addresses', []):
            address = entry['address'] if isinstance(entry, dict) else entry
            prefix = entry.get('prefix', 24) if isinstance(entry, dict) else 24
            if is_lan_address(address):
                network = ViewerNetwork(name, address, kind, prefix)
                old = result.get(address)
                if old is None or rank(network) < rank(old):
                    result[address] = network
    return sorted(result.values(), key=rank)


def rank(network):
    return ({'hotspot': 0, 'wifi': 1, 'ethernet': 2}[network.kind], network.name, network.address)


def hotspot_conflicts(networks):
    return [ap.address for ap in networks if ap.kind == 'hotspot' and any(
        other.kind == 'ethernet' and IPv4Network((ap.address, ap.prefix), strict=False).overlaps(
            IPv4Network((other.address, other.prefix), strict=False)) for other in networks)]


def hotspot_pool_issue(address, subnets):
    """Validate the actual macOS DHCP pool, not just the bridge's own address."""
    for subnet in subnets:
        if address not in subnet.get('dhcp_router', []):
            continue
        try:
            network = IPv4Network((subnet['net_address'], subnet['net_mask']))
            start, end = map(IPv4Address, subnet['net_range'])
            if not (network.network_address < start <= end < network.broadcast_address):
                return 'Wi-Fi не выдаёт адреса · проверьте диапазон раздачи.'
            if start <= IPv4Address(address) <= end:
                return 'Адрес станции попал в диапазон раздачи Wi-Fi.'
        except (ValueError, TypeError, KeyError):
            return 'Некорректные параметры выдачи адресов Wi-Fi.'
    return ''


def local_hotspot_issue(networks):
    if hotspot_conflicts(networks):
        return 'Адреса раздачи и кабеля совпадают · нужна отдельная подсеть Wi-Fi.'
    import sys
    hotspot = next((item for item in networks if item.kind == 'hotspot'), None)
    if hotspot and sys.platform == 'darwin':
        import plistlib
        try:
            with open('/etc/bootpd.plist', 'rb') as stream:
                return hotspot_pool_issue(hotspot.address, plistlib.load(stream).get('Subnets', []))
        except (OSError, ValueError, plistlib.InvalidFileException):
            pass
    return ''


def local_viewer_networks():
    from PySide6.QtNetwork import QNetworkInterface
    flags = QNetworkInterface.InterfaceFlag
    kinds = QNetworkInterface.InterfaceType
    return viewer_networks([
        dict(name=item.name(), running=bool(item.flags() & flags.IsUp and item.flags() & flags.IsRunning),
             point_to_point=bool(item.flags() & flags.IsPointToPoint),
             kind='wifi' if item.type() == kinds.Wifi else 'ethernet' if item.type() == kinds.Ethernet else '',
             addresses=[dict(address=entry.ip().toString(), prefix=entry.prefixLength()) for entry in item.addressEntries()])
        for item in QNetworkInterface.allInterfaces()
    ])
