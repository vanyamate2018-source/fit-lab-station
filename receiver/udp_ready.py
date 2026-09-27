"""Wait for a child to claim its UDP input before allocating another port."""
import errno
import socket
import time


def wait_for_udp_receiver(child, port, timeout=3):
    deadline = time.monotonic() + timeout
    while child.poll() is None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                probe.bind(('0.0.0.0', port))
            except OSError as exc:
                if exc.errno == errno.EADDRINUSE:
                    return
                raise
        if time.monotonic() >= deadline:
            raise ValueError('Приёмник не открыл локальный вход UDP')
        time.sleep(.01)
    raise ValueError('Приёмник завершился до открытия локального входа UDP')
