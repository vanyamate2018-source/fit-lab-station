"""The viewer must start without DNS, including on isolated receiver networks."""
from unittest.mock import patch
from urllib.request import urlopen

from master.viewer_server import serve_viewer


def test_viewer_starts_and_serves_without_reverse_dns():
    with patch('socket.getfqdn', side_effect=AssertionError('Unexpected DNS lookup')):
        server = serve_viewer('127.0.0.1', 0, status=lambda: {'state': 'stopped'})
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/status.json', timeout=2) as response:
                assert response.status == 200
                assert b'"state": "stopped"' in response.read()
        finally:
            server.shutdown()
            server.server_close()
