"""Prepare complete private role sources, without claiming target installers."""
import hashlib
import json
from pathlib import Path
import shutil


def main():
    project = Path(__file__).resolve().parents[1]
    destination = project.parent / 'deployment'
    from tools.save_checkpoint import copy_sources
    for role, label in (('master', 'МАСТЕР'), ('receiver', 'ПРИЁМНИК')):
        root = destination / role
        staging = root / 'source-next'
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for name in ('master', 'receiver', 'shared', 'control', 'sdr', 'simulator', 'tools', 'docs', 'tests', 'deployment'):
            if (project / name).is_dir():
                copy_sources(project / name, staging / name)
        for name in ('pyproject.toml', 'README.md', 'PROGRESS.md'):
            if (project / name).is_file():
                shutil.copy2(project / name, staging / name)
        files = [dict(path=str(p.relative_to(staging)), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in sorted(staging.rglob('*')) if p.is_file()]
        source = root / 'source'
        if source.exists():
            shutil.rmtree(source)
        staging.rename(source)
        payload = dict(schema=2, role=role, interface='full_on_both_roles',
            status='source_preparation_not_installable_image', installable=False,
            secrets_included=False, hardware_profile_required=True, files=files)
        (root / 'manifest.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
        (root / 'role.json').write_text(json.dumps(dict(schema=1, role=role,
            module_name='Видеомодуль WFB', full_local_interface=True,
            desired_mode='control_station' if role == 'master' else 'receiver_service',
            status='target_configuration_pending', autostart_enabled=False), ensure_ascii=False, indent=2)+'\n')
        (root / 'README.md').write_text(f'# {label}\n\n'
            'Закрытый комплект исходников. Не установщик и не готовый образ платы.\n\n'
            + ('Мастер управляет выбранным видеомодулем: встроенным USB или по LAN.\n' if role == 'master' else
               'Приёмник обслуживает USB/RF, видео и команды. Полный локальный интерфейс сохранён для проверки и настройки.\n') +
            'Роли не меняются при появлении другого устройства. Передача управления требует завершения сетевого протокола.\n\n'
            'Для целевого устройства нужны модель платы, архитектура, ОС, драйвер Wi-Fi и проверка декодера.\n'
            'Mac/Windows/Linux требуют отдельных сборок; папки platforms содержат планы, не бинарники.\n'
            'Ключи и пароли не включены. Сохранением доступа управляет приложение через защищённое хранилище ОС.\n'
            'Linux без графического сеанса требует настроенного Secret Service либо отдельного системного защищённого хранилища. Открытого запасного файла нет.\n'
            'Автозапуск не установлен. Зависимости требуют проверки на целевом оборудовании.\n', encoding='utf-8')
        for item in files:
            assert hashlib.sha256((source / item['path']).read_bytes()).hexdigest() == item['sha256']
    print('Комплекты МАСТЕР и ПРИЁМНИК обновлены; контрольные суммы проверены; секреты исключены.')


if __name__ == '__main__':
    main()
