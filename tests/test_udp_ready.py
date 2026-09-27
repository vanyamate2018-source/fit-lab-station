import socket
import subprocess
import sys
from unittest.mock import Mock

import pytest
from receiver.udp_ready import wait_for_udp_receiver


def test_wait_until_child_owns_port_before_next_allocation():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    script = 'import socket,time,sys;time.sleep(.1);s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(("0.0.0.0",int(sys.argv[1])));time.sleep(10)'
    child = subprocess.Popen([sys.executable, '-c', script, str(port)])
    try:
        wait_for_udp_receiver(child, port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(('127.0.0.1', 0))
            assert s.getsockname()[1] != port
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_failed_child_is_not_reported_ready():
    with pytest.raises(ValueError, match='завершился'):
        wait_for_udp_receiver(Mock(poll=Mock(return_value=1)), 12345)


def test_alive_child_without_input_times_out():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    with pytest.raises(ValueError, match='не открыл'):
        wait_for_udp_receiver(Mock(poll=Mock(return_value=None)), port, timeout=0)
