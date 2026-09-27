from unittest.mock import Mock, patch
from master import camera_session as pool


def test_exclusive_reuse_and_probe():
    pool.close_all()
    first, second = Mock(), Mock()
    connect = Mock(side_effect=[first, second])
    a = pool.acquire(('camera',), connect)
    b = pool.acquire(('camera',), connect)
    assert a.client is first and b.client is second
    a.close()
    with patch('master.camera_radio.command', return_value=(0, '')) as probe:
        c = pool.acquire(('camera',), connect)
    assert c.client is first and connect.call_count == 2
    probe.assert_called_once_with(first, 'true', timeout=2)
    b.close(); c.close(); pool.close_all()


def test_dead_replaced():
    pool.close_all()
    old, new = Mock(), Mock()
    pool.acquire(('camera',), lambda: old).close()
    with patch('master.camera_radio.command', side_effect=TimeoutError):
        b = pool.acquire(('camera',), lambda: new)
    old.close.assert_called_once()
    assert b.client is new
    b.close(); pool.close_all()


def test_failed_operation_discarded():
    pool.close_all()
    client = Mock()
    a = pool.acquire(('camera',), lambda: client)
    try:
        raise TimeoutError()
    except TimeoutError:
        a.close()
    assert not pool._idle
    client.close.assert_called_once()


def test_changed_identity_discards_old():
    pool.close_all()
    old = Mock()
    pool.acquire(('old-pin',), lambda: old).close()
    new = pool.acquire(('new-pin',), Mock)
    old.close.assert_called_once()
    new.close(); pool.close_all()
