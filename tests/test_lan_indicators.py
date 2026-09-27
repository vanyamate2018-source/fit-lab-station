import threading
import time
from master.lan_indicators import LanIndicators


def test_unreachable_led_endpoint_does_not_block_radio_updates(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def connect(*args, **kwargs):
        entered.set()
        release.wait(1)
        raise OSError('LAN disconnected')
    monkeypatch.setattr('master.lan_indicators.socket.create_connection', connect)
    sender = LanIndicators(('192.0.2.1', 60401))
    try:
        sender.update([{'connection': 'receiving'}, {'connection': 'waiting'}])
        assert entered.wait(1)
        before = time.monotonic()
        for _ in range(100):
            sender.update([{'connection': 'waiting'}, {'connection': 'receiving'}])
        assert time.monotonic() - before < .1
        assert b'false, true' in sender.payload
    finally:
        release.set()
        sender.close()
    assert not sender.worker.is_alive()
