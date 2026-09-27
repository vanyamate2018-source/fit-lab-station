"""Offline release contents shared by packaging and the setup window."""
COMPONENTS = (
    ('station', 'FIT-LAB Station', 'Приложение и интерфейс'),
    ('runtime', 'Среда запуска', 'Все библиотеки для запуска без установки Python'),
    ('media', 'Видео и звук', 'Декодирование, запись и веб-трансляция'),
    ('radio', 'Видеомодуль WFB', 'Приёмники и обратный канал'),
    ('touch', 'Поддержка сенсора', 'Компонент для подключённого экрана'),
)


def release_plan():
    return {
        'schema': 1, 'distribution': 'offline_bundle',
        'status': 'awaiting_self_contained_packages', 'installable': False,
        'preserve_development_ssd': True,
        'include_camera_secrets': False,
        'components': [{'id': key, 'name': name, 'description': description,
                        'status': 'not_packaged', 'bytes': None}
                       for key, name, description in COMPONENTS],
        'steps': ['Проверка устройства', 'Проверка компонентов',
                  'Установка файлов', 'Проверка запуска', 'Готово'],
    }
