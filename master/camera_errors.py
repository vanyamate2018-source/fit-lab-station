"""Short user-facing connection messages; raw failures stay in diagnostics."""


def connection_message(message):
    text = str(message)
    lowered = text.lower()
    if 'no existing session' in lowered or 'connection reset' in lowered or lowered == 'eof':
        return 'Соединение с камерой прервано'
    if 'timed out' in lowered or 'timeout' in lowered or 'ssh protocol banner' in lowered:
        return 'Камера не ответила на подключение'
    if 'connection refused' in lowered:
        return 'Служба управления камерой недоступна'
    return text
