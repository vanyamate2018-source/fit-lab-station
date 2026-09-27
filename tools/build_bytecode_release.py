"""Build a Python-version-specific application bundle without plain Python sources."""
import hashlib
import json
import py_compile
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile


def build(source, output):
    if sys.version_info[:2] != (3, 10):
        raise RuntimeError('Build this receiver bundle with Python 3.10')
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fitlab-build-') as temp:
        stage = Path(temp) / 'application'
        stage.mkdir()
        for package in ('master', 'receiver', 'shared'):
            for path in (source/package).rglob('*'):
                rel = path.relative_to(source)
                if not path.is_file() or path.is_symlink() or '__pycache__' in rel.parts or path.name.startswith('._'):
                    continue
                if path.suffix in ('.pyc', '.pyo'):
                    continue
                target = stage/rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix == '.py':
                    py_compile.compile(str(path), cfile=str(target.with_suffix('.pyc')),
                                       dfile=rel.as_posix(), doraise=True)
                else:
                    shutil.copy2(path, target)
        manifest = {str(p.relative_to(stage)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in stage.rglob('*') if p.is_file()}
        assert not list(stage.rglob('*.py'))
        (stage/'release.json').write_text(json.dumps(dict(format='fitlab-bytecode-v1', python='3.10', files=manifest), indent=2))
        with tarfile.open(output/'application.tar.gz', 'w:gz') as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_file(): archive.add(path, arcname=path.relative_to(stage))
        (output/'application.sha256').write_text(hashlib.sha256((output/'application.tar.gz').read_bytes()).hexdigest()+'  application.tar.gz\n')
        print('Built', len(manifest), 'files, no plain Python application sources')


if __name__ == '__main__':
    build(*sys.argv[1:])
