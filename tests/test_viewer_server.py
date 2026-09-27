import json
import struct
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

import pytest
from master.viewer_server import serve_viewer


@pytest.fixture
def viewer():
    server = serve_viewer('127.0.0.1', 0)
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()


def test_manifest_and_home_screen_icon_are_served(viewer):
    client = build_opener(ProxyHandler({}))
    with client.open(viewer+'/manifest.webmanifest') as response:
        assert response.headers.get_content_type() == 'application/manifest+json'
        manifest = json.load(response)
    with client.open(viewer+manifest['icons'][0]['src']) as response:
        png = response.read()
        assert response.headers.get_content_type() == 'image/png'
        assert png.startswith(b'\x89PNG')
        assert struct.unpack('>II', png[16:24]) == (512, 512)
    with client.open(Request(viewer+'/', method='HEAD')) as response:
        assert int(response.headers['Content-Length']) > 0
        assert not response.read()
    assert manifest['display'] == 'standalone'


@pytest.mark.parametrize('path', ['/../private/gs.key', '/%2e%2e/private/gs.key', '/viewer_server.py', '/assets/', '/settings'])
def test_viewer_never_exposes_files_or_camera_settings(viewer, path):
    with pytest.raises(HTTPError) as error:
        build_opener(ProxyHandler({})).open(viewer+path)
    assert error.value.code == 404
