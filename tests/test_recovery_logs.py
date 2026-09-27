from receiver.recovery import Job
from receiver.resilient_radio import Backend


def test_reused_usb_address_can_initialize_without_log_directory_collision(tmp_path):
    backend = Backend(tmp_path, {}, [10001, 10002])
    backend.spawn = lambda command, path: path
    device = {"location": 10, "address": 7}
    unplugged = Job(device, attempt=1)
    reconnected = Job(device, attempt=1)
    first = backend.prepare(unplugged)
    second = backend.prepare(reconnected)
    assert first != second
    assert first.parent.is_dir() and second.parent.is_dir()
