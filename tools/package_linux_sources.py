"""Build and verify Linux source archives; publish locally only with --apply.

Run from project: python -m tools.package_linux_sources [--apply]
Default execution uses a temporary directory and leaves existing packages intact.
Archives have stable ordering, timestamps, ownership and gzip headers.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile

from tools.save_checkpoint import permitted


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def source_files(project, roots):
    result = []
    for name in roots:
        root = project / name
        if not root.exists() or root.is_symlink():
            raise ValueError('Missing or linked source root: ' + name)
        candidates = [root] if root.is_file() else root.rglob('*')
        for path in candidates:
            rel = path.relative_to(project)
            if (not path.is_file() or any((project / Path(*rel.parts[:i])).is_symlink()
                                         for i in range(1, len(rel.parts)+1))):
                continue
            if (not permitted(rel) or any(part.lower() in {'data', 'private', 'secrets', 'venv', '.venv'}
                                          or part.startswith('._') for part in rel.parts)
                    or path.suffix.lower() in {'.pyc', '.pyo', '.key', '.pem', '.p12', '.pfx', '.keystore'}):
                continue
            result.append((rel.as_posix(), path))
    return sorted(result)


def build_archive(target, files):
    with target.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, path in files:
                info = tarfile.TarInfo(name)
                info.size = path.stat().st_size
                info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                with path.open('rb') as source:
                    archive.addfile(info, source)


def verify_archive(archive_path, files, extraction):
    expected = dict(files)
    extraction.mkdir()
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        if len(members) != len(expected) or {m.name for m in members} != set(expected):
            raise ValueError('Archive contents differ from selected sources')
        for member in members:
            name = Path(member.name)
            if not member.isfile() or name.is_absolute() or '..' in name.parts:
                raise ValueError('Unsafe archive member')
            target = extraction / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            if digest(target) != digest(expected[member.name]):
                raise ValueError('Extracted source mismatch: ' + member.name)


def publish(source, target):
    fd, name = tempfile.mkstemp(prefix='.' + target.name + '-', dir=target.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        staged.chmod(0o644)
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Replace local archives and Linux checksums after verification')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    root = project.parent
    package = root / 'Установка FIT-LAB/Приёмник Linux'
    checksum_path = package / 'checksums.json'
    checksums = json.loads(checksum_path.read_text())
    if 'source.tar.gz' not in checksums:
        raise ValueError('Missing source archive checksum')
    # Refuse unrelated package drift rather than silently blessing changed runtime files.
    for name, expected in checksums.items():
        path = package / name
        if Path(name).name != name or path.is_symlink() or digest(path) != expected:
            raise ValueError('Existing package checksum mismatch: ' + name)
    with tempfile.TemporaryDirectory(prefix='fitlab-linux-package-') as temporary:
        work = Path(temporary)
        jobs = [
            ('source.tar.gz', package / 'source.tar.gz', ('master', 'receiver', 'shared')),
            ('receiver-gui-source.tar.gz', root / 'deployment/receiver-gui-source.tar.gz',
             ('master', 'receiver', 'shared', 'control', 'sdr', 'simulator', 'pyproject.toml')),
        ]
        for name, target, roots in jobs:
            files = source_files(project, roots)
            build_archive(work / name, files)
            verify_archive(work / name, files, work / (name + '-extracted'))
            build_archive(work / (name + '.repeat'), files)
            if digest(work / name) != digest(work / (name + '.repeat')):
                raise ValueError('Archive is not reproducible')
            print(f'{name}: {len(files)} files; extraction, hashes and reproducibility verified')
        checksums['source.tar.gz'] = digest(work / 'source.tar.gz')
        companions = ('install.sh', 'launch.sh', 'verify.py', 'hotspot-helper.sh', 'install-hotspot-helper.sh')
        for name in companions:
            source = project / 'deployment/linux-station' / name
            if source.is_symlink() or not source.is_file():
                raise ValueError('Missing or linked installer companion: ' + name)
            shutil.copyfile(source, work / name)
            checksums[name] = digest(work / name)
            if checksums[name] != digest(source):
                raise ValueError('Installer companion copy mismatch: ' + name)
        staged_checksums = work / 'checksums.json'
        staged_checksums.write_text(json.dumps(checksums, ensure_ascii=False, indent=2) + '\n')
        for name, expected in json.loads(staged_checksums.read_text()).items():
            candidate = work / name if name == 'source.tar.gz' or name in companions else package / name
            if digest(candidate) != expected:
                raise ValueError('Updated package checksum mismatch: ' + name)
        if args.apply:
            for name, target, _ in jobs:
                publish(work / name, target)
            for name in companions:
                publish(work / name, package / name)
                if name.endswith('.sh'):
                    (package / name).chmod(0o755)
            publish(staged_checksums, checksum_path)
            print('Local archives and checksums updated; no installation or service restart performed.')
        else:
            print('Verification only: existing archives and checksums unchanged. Use --apply to update.')


if __name__ == '__main__':
    main()
