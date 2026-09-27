"""Staging of signed runtime packages. Does not install or execute downloads.

The release application must pin the verification key and serialize calls per
cache directory. Never trust a public key delivered alongside a remote catalog.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


def https_url(value):
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Пакет должен иметь адрес HTTPS без учётных данных')
    return value


class SecureRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        https_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class RuntimePackage:
    name: str
    version: str
    url: str
    sha256: str
    size: int

    def __post_init__(self):
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', self.name):
            raise ValueError('Некорректное имя компонента')
        if not re.fullmatch(r'[a-f0-9]{64}', self.sha256):
            raise ValueError('Не задана проверочная сумма компонента')
        if type(self.size) is not int or not 0 < self.size <= 2 * 1024**3:
            raise ValueError('Некорректный размер компонента')
        https_url(self.url)


def verified_packages(catalogue: bytes, signature: bytes, public_key: bytes, target: str):
    """Only an already trusted, pinned release key may authorize package hashes."""
    from nacl.signing import VerifyKey
    if len(catalogue) > 1024 * 1024:
        raise ValueError('Слишком большой каталог обновления')
    VerifyKey(public_key).verify(catalogue, signature)
    data = json.loads(catalogue)
    if data.get('schema') != 1 or data.get('target') != target:
        raise ValueError('Пакет предназначен для другого устройства')
    items = data.get('packages')
    if not isinstance(items, list) or not 1 <= len(items) <= 32:
        raise ValueError('В каталоге нет готовых пакетов')
    result, names = [], set()
    for entry in items:
        package = RuntimePackage(**entry)
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', package.name) or package.name in names:
            raise ValueError('Некорректное имя компонента')
        if not isinstance(package.version, str) or not package.version or len(package.version) > 64:
            raise ValueError('Некорректная версия компонента')
        if not re.fullmatch(r'[a-f0-9]{64}', package.sha256):
            raise ValueError('Не задана проверочная сумма компонента')
        if type(package.size) is not int or not 0 < package.size <= 2 * 1024**3:
            raise ValueError('Некорректный размер компонента')
        https_url(package.url)
        names.add(package.name)
        result.append(package)
    return result


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stage_package(package, cache: Path, progress=None, opener=None):
    """Resume an interrupted transfer, verify it, then atomically mark ready.

    Cached bytes are named by the signed hash, not by a remote filename. A failed
    transfer remains .part; no caller may execute it. Cancellation in progress()
    also leaves a resumable partial file. Updates are staged outside active media.
    """
    https_url(package.url)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (package.sha256 + '.package')
    partial = cache / (package.sha256 + '.part')
    if target.is_symlink() or partial.is_symlink():
        raise ValueError('Недопустимый путь кэша')
    if target.exists():
        if target.stat().st_size == package.size and digest(target) == package.sha256:
            if progress: progress(package.size, package.size)
            return target
        target.unlink()
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > package.size:
        partial.unlink()
        offset = 0
    if offset < package.size:
        request = Request(package.url, headers={'Accept-Encoding': 'identity'})
        if offset:
            request.add_header('Range', f'bytes={offset}-')
        client = opener or build_opener(SecureRedirect())
        with client.open(request, timeout=15) as response:
            https_url(response.geturl())
            if response.headers.get('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Сервер изменил формат пакета')
            if response.status == 206:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                expected = (offset, package.size - 1, package.size)
                if not match or tuple(map(int, match.groups())) != expected:
                    raise ValueError('Сервер не подтвердил продолжение загрузки')
            elif response.status == 200:
                offset = 0  # Server ignored Range; replace the incomplete file.
            else:
                raise ValueError('Сервер не выдал пакет')
            if response.headers.get('Content-Length') is not None:
                if int(response.headers['Content-Length']) != package.size - offset:
                    raise ValueError('Размер ответа не совпадает с каталогом')
            with partial.open('ab' if offset else 'wb') as stream:
                partial.chmod(0o600)
                while block := response.read(256 * 1024):
                    if offset + len(block) > package.size:
                        raise ValueError('Размер пакета превышает каталог')
                    stream.write(block)
                    offset += len(block)
                    if progress: progress(offset, package.size)
        if offset != package.size:
            raise OSError('Загрузка прервана; продолжим при следующей попытке')
    if digest(partial) != package.sha256:
        partial.unlink()
        raise ValueError('Проверка пакета не пройдена; установка отменена')
    partial.replace(target)
    return target
