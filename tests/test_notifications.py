from master.notifications import NotificationQueue


def test_same_state_does_not_restart_toast_but_real_transition_does():
    q=NotificationQueue()
    assert q.push('Связь с мастером потеряна',100)
    assert q.take(100)=='Связь с мастером потеряна'
    assert not q.push('Связь с мастером потеряна',120)
    assert q.push('Связь с мастером восстановлена',121)
    assert q.take(121)=='Связь с мастером восстановлена'
    assert q.push('Связь с мастером потеряна',122)
    assert q.take(122)=='Связь с мастером потеряна'


def test_delivery_collapses_obsolete_states_and_prioritizes_errors():
    q=NotificationQueue();q.push('Настройки применены',100);q.take(100)
    q.push('Запись начата',101);q.push('Запись остановлена',102)
    assert q.take(102) is None
    q.push('Ошибка записи: накопитель отключён',103)
    assert q.take(103).startswith('Ошибка записи')
    assert q.take(107)=='Запись остановлена'
    assert q.take(200) is None


def test_old_messages_expire_and_queue_is_bounded():
    q=NotificationQueue()
    for i in range(50):q.push('Событие %d'%i,100)
    assert len(q.pending)<=8
    assert q.take(120) is None
