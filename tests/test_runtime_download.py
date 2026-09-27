import hashlib
import io
import json
from dataclasses import replace

import pytest
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey

from shared.runtime_download import RuntimePackage, stage_package, verified_packages


CONTENT = b'component-payload-for-test'
PACKAGE = RuntimePackage('media', '1.0', 'https://example.com/media', hashlib.sha256(CONTENT).hexdigest(), len(CONTENT))


class Response(io.BytesIO):
    def __init__(self, content=CONTENT, status=200, headers=None, url=PACKAGE.url):
        super().__init__(content)
        self.status, self.headers, self.url = status, headers or {}, url

    def geturl(self):
        return self.url


class Client:
    def __init__(self, response):
        self.response, self.request = response, None

    def open(self, request, timeout):
        self.request = request
        return self.response


def test_catalogue_signature_and_device_match():
    from dataclasses import asdict
    key = SigningKey.generate()
    body = json.dumps(dict(schema=1, target='windows-x86_64-master', packages=[asdict(PACKAGE)])).encode()
    signed = key.sign(body)
    assert verified_packages(body, signed.signature, bytes(key.verify_key), 'windows-x86_64-master') == [PACKAGE]
    with pytest.raises(BadSignatureError):
        verified_packages(body + b' ', signed.signature, bytes(key.verify_key), 'windows-x86_64-master')
    with pytest.raises(ValueError, match='другого устройства'):
        verified_packages(body, signed.signature, bytes(key.verify_key), 'linux-arm64-receiver')


def test_resume_download_and_reuse_verified_cache(tmp_path):
    partial = tmp_path / (PACKAGE.sha256 + '.part')
    partial.write_bytes(CONTENT[:7])
    client = Client(Response(CONTENT[7:], 206, {'Content-Range': f'bytes 7-{len(CONTENT)-1}/{len(CONTENT)}'}))
    ready = stage_package(PACKAGE, tmp_path, opener=client)
    assert client.request.get_header('Range') == 'bytes=7-'
    assert ready.read_bytes() == CONTENT and not partial.exists()
    assert stage_package(PACKAGE, tmp_path, opener=None) == ready


def test_range_ignored_restarts_without_duplicating_bytes(tmp_path):
    (tmp_path / (PACKAGE.sha256 + '.part')).write_bytes(CONTENT[:5])
    assert stage_package(PACKAGE, tmp_path, opener=Client(Response())).read_bytes() == CONTENT


@pytest.mark.parametrize('response', [
    lambda: Response(CONTENT, 206, {'Content-Range': 'bytes 5-100/101'}),
    lambda: Response(CONTENT + b'extra'),
    lambda: Response(CONTENT, url='http://example.com/media'),
    lambda: Response(CONTENT, headers={'Content-Encoding': 'gzip'}),
    lambda: Response(CONTENT, headers={'Content-Length': '999'}),
])
def test_untrusted_transfer_is_never_marked_ready(tmp_path, response):
    with pytest.raises(ValueError):
        stage_package(PACKAGE, tmp_path, opener=Client(response()))
    assert not list(tmp_path.glob('*.package'))


def test_interrupted_download_remains_resumable(tmp_path):
    with pytest.raises(OSError, match='прервана'):
        stage_package(PACKAGE, tmp_path, opener=Client(Response(CONTENT[:9])))
    assert (tmp_path / (PACKAGE.sha256 + '.part')).read_bytes() == CONTENT[:9]


def test_hash_failure_never_installs_and_discards_corrupt_partial(tmp_path):
    with pytest.raises(ValueError, match='Проверка пакета'):
        stage_package(PACKAGE, tmp_path, opener=Client(Response(b'x' * len(CONTENT))))
    assert not list(tmp_path.iterdir())


def test_corrupt_cached_package_is_replaced(tmp_path):
    (tmp_path / (PACKAGE.sha256 + '.package')).write_bytes(b'x' * len(CONTENT))
    assert stage_package(PACKAGE, tmp_path, opener=Client(Response())).read_bytes() == CONTENT


def test_symlink_cache_is_not_followed(tmp_path):
    outside = tmp_path / 'unrelated'
    outside.write_bytes(b'leave intact')
    (tmp_path / (PACKAGE.sha256 + '.part')).symlink_to(outside)
    with pytest.raises(ValueError, match='путь'):
        stage_package(PACKAGE, tmp_path, opener=Client(Response()))
    assert outside.read_bytes() == b'leave intact'
