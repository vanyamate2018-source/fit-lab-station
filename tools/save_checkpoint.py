"""Save a private SSD checkpoint without credentials, caches or recordings."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
from datetime import datetime


SKIP = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'node_modules',
        'target', 'build', 'dist', 'private', 'secrets', 'recordings', 'logs',
        'telemetry', '.DS_Store', '.env'}
SECRET_SUFFIXES = {'.key', '.pem', '.p12', '.pfx', '.keystore'}


def permitted(path):
    return not any(p in SKIP or p.endswith('.egg-info') or p.startswith('.env.')
                   for p in path.parts) and path.suffix not in SECRET_SUFFIXES


def copy_sources(source, target):
    for root, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [name for name in dirs if permitted(Path(root, name).relative_to(source))
                   and not Path(root, name).is_symlink()]
        for name in files:
            path = Path(root, name)
            rel = path.relative_to(source)
            if not path.is_symlink() and permitted(rel) and path.suffix not in {'.pyc', '.pyo'}:
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    os.umask(0o077)
    project = Path(__file__).resolve().parents[1]
    ssd = project.parent
    stamp = datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S')
    folder = ssd / 'FIT-LAB — комплект для переноса' / stamp
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    folder.parent.chmod(0o700)
    copy_sources(project, folder / '04 - ПРОЕКТ (закрытый)/project')
    copy_sources(ssd / 'experiments', folder / '04 - ПРОЕКТ (закрытый)/experiments')
    copy_sources(ssd / 'deployment', folder / '04 - ПРОЕКТ (закрытый)/deployment')
    shutil.copytree(ssd / 'data/exports/FIT-LAB - руководство', folder / '01 - ДОКУМЕНТЫ PDF')
    checks = folder / '06 - ПРОВЕРКИ'
    checks.mkdir()
    for name in ('tests-wifi-release-20260926.log', 'viewer-player-20260926.log',
                 'led-check-20260926.json', 'wifi-hotspot-live-20260926.json',
                 'wifi-with-web-20260926.json', 'web-decode-20260926.log',
                 'wifi-layout-check.log', 'wifi-subnet-result.log'):
        shutil.copy2(ssd / 'data/exports' / name, checks / name)
    for name in ('tests-auto-selection-20260926.log', 'viewer-final-20260926.log',
                 'layout-security-final-20260926.log', 'camera-onboarding-20260926.json',
                 'tests-final-delivery-20260926.log', 'tests-viewer-audio-final-20260926.log',
                 'audio-radio-live-20260926.json', 'live-final-delivery-20260926.json',
                 'live-final-followup-20260926.json', 'radio-readback-final-20260926.json'):
        source = ssd / 'data/exports' / name
        if source.is_file():
            shutil.copy2(source, checks / name)
    for role, title in (('master', '02 - МАСТЕР (исходники)'), ('receiver', '03 - ПРИЁМНИК (исходники)')):
        copy_sources(ssd / 'deployment' / role, folder / title)
    (folder / '05 - MAC (архив текущей сборки)').mkdir()
    web = folder / '07 - ВЕБ (iPhone Android ПК)'
    web.mkdir()
    for asset in ('viewer.html', 'viewer-recorder.js', 'viewer-install.js', 'viewer.webmanifest', 'viewer-icon.png', 'viewer-favicon.png'):
        shutil.copy2(project / 'master/assets' / asset, web / asset)
    (web / 'ПРОЧИТАТЬ.txt').write_text('Откройте http://192.168.50.1:8890/ в сети FIT-LAB при запущенной трансляции.\nЭто локальное веб-приложение, не IPA и не APK.\nИконка: кнопка «На главный экран»; инструкции для iPhone, Android и ПК внутри страницы.\nФайлы этой папки обслуживает Station; открытие viewer.html с диска не создаёт сервер трансляции.\nВеб-трансляция и запись пока только видео; звук воспроизводится на мастере.\n')
    # App bundles are archived, not installed as duplicate Dock applications.
    with tarfile.open(folder / '05 - MAC (архив текущей сборки)/Приложения Mac.tar.gz', 'w:gz') as archive:
        for name in ('FIT-LAB Station.app', 'FIT-LAB Touch.app'):
            archive.add(ssd / name, arcname=name)
    runtime = folder / '05 - MAC (архив текущей сборки)/Бинарные модули Mac'
    runtime.mkdir()
    for source in (ssd / 'tools/mediamtx/mediamtx',
                   ssd / 'experiments/wfb-link/target/release/wfb-radio-diag',
                   ssd / 'experiments/wfb-link/target/release/wfb-radio-ssh',
                   ssd / 'experiments/wfb-link/target/wfb-ng-macos/bin/wfb_rx',
                   ssd / 'experiments/wfb-ng-codec-c1a160c4/wfb_tx'):
        if source.is_file():
            shutil.copy2(source, runtime / source.name)
    (folder / '00 - ПРОЧИТАТЬ ПЕРЕД ПЕРЕНОСОМ.txt').write_text(
        'FIT-LAB — закрытый комплект владельца\n\n'
        f'Дата: {stamp}\n'
        '01 - ДОКУМЕНТЫ PDF: новая инструкция, полный чек-лист, отчёт со структурой и программами.\n'
        '02 - МАСТЕР: полный исходный комплект для мастер-пульта.\n'
        '03 - ПРИЁМНИК: полный исходный комплект приёмника, с тем же локальным интерфейсом.\n'
        '04 - ПРОЕКТ: исходный проект, радиокомпоненты и планы платформ. НЕ ПУБЛИКОВАТЬ.\n'
        '05 - MAC: архив текущих приложений и бинарных модулей.\n'
        '06 - ПРОВЕРКИ: результаты проверок.\n'
        '07 - ВЕБ: локальный плеер для iPhone, Android и ПК.\n\n'
        'ГОТОВО К ЗАПУСКУ: текущий Mac с подключённым SSD, /Volumes/FIT-LAB/FIT-LAB Station.app.\n'
        'Проект остаётся на исходном месте: /Volumes/FIT-LAB/project.\n'
        'Готовых автономных установщиков Windows/Linux и образа одноплатника ещё НЕТ.\n'
        'Для переноса можно копировать весь этот каталог; установка на другой компьютер требует сборки и проверки зависимостей.\n'
        'Mac-приложение пока связано с /Volumes/FIT-LAB и установленным Homebrew/Python. Архив не автономный установщик.\n\n'
        'Ключи и пароли намеренно исключены. Пароли сохранены приложением в Связке ключей этого Mac.\n'
        'Перенос доверенных камер требует отдельного зашифрованного экспорта — он ещё не реализован.\n'
        'Не удалять исходный SSD и доступ к Связке ключей. Записи, журналы сеансов и кэш сюда не копировались.\n'
        'Код и документы не загружались во внешние сервисы. Доступ к каталогу ограничен владельцем.\n', encoding='utf-8')
    files = [dict(path=str(p.relative_to(folder)), bytes=p.stat().st_size, sha256=sha256(p))
             for p in sorted(folder.rglob('*')) if p.is_file()]
    manifest = dict(created_at=datetime.now().astimezone().isoformat(),
                    kind='private_source_checkpoint_not_installer', files=files)
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    for entry in files:
        if sha256(folder / entry['path']) != entry['sha256']:
            raise RuntimeError('Checkpoint verification failed')
    print(json.dumps(dict(folder=str(folder), files=len(files),
                          bytes=sum(f['bytes'] for f in files), verified=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
