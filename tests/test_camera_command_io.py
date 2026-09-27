from unittest.mock import Mock

import pytest

from master.camera_radio import command


class Channel:
    def __init__(self, out=b'answer', err=b'', exiting=True):
        self.out, self.err, self.exiting = out, err, exiting
        self.closed = False

    def recv_ready(self):
        return bool(self.out)

    def recv(self, n):
        value, self.out = self.out[:n], self.out[n:]
        return value

    def recv_stderr_ready(self):
        return bool(self.err)

    def recv_stderr(self, n):
        value, self.err = self.err[:n], self.err[n:]
        return value

    def exit_status_ready(self):
        return self.exiting and not self.err

    def recv_exit_status(self):
        assert self.exit_status_ready()
        return 0

    def close(self):
        self.closed = True


def client_for(channel):
    client = Mock()
    client.exec_command.return_value = Mock(), Mock(channel=channel), Mock()
    return client


def test_stderr_is_drained_without_exposing_it():
    channel = Channel(err=b'private diagnostic' * 2000)
    assert command(client_for(channel), 'fixed command') == (0, 'answer')
    assert channel.closed


def test_missing_exit_status_cannot_hang_dispatcher():
    channel = Channel(exiting=False)
    with pytest.raises(TimeoutError):
        command(client_for(channel), 'fixed command', timeout=.03)
    assert channel.closed


@pytest.mark.parametrize('field', ['out', 'err'])
def test_oversized_output_is_bounded(field):
    channel = Channel(**{field: b'x' * 100})
    with pytest.raises(ValueError):
        command(client_for(channel), 'fixed command', limit=32)
    assert channel.closed
