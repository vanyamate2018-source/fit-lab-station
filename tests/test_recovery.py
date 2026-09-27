from receiver.recovery import RadioRecovery, RX_MACS


class Process:
    def __init__(self):
        self.code = None
        self.terminated = 0
    def poll(self):
        return self.code
    def terminate(self):
        self.terminated += 1
        self.code = 0
    def kill(self):
        self.code = -9


class Backend:
    def __init__(self):
        self.preparations = []
        self.radios = []
    def prepare(self, job):
        process = Process()
        self.preparations.append((job.device.copy(), process))
        return process
    def profile(self, job):
        return RX_MACS[job.device['location'] - 100], {}
    def receive(self, job):
        process = Process()
        self.radios.append((job.index, process))
        return process
    def finish(self, job):
        pass


D1, D2 = dict(location=100, address=4), dict(location=101, address=10)


def ready():
    backend = Backend()
    manager = RadioRecovery(backend)
    manager.tick(0, [D1, D2])
    manager.tick(.1)
    for _, process in backend.preparations:
        process.code = 0
    manager.tick(.2)
    return manager, backend


def test_unplug_and_new_usb_address_does_not_restart_other_rx():
    manager, backend = ready()
    rx2 = backend.radios[1][1]
    manager.tick(1, [D2])
    assert manager.receivers[0]['connection'] == 'disconnected'
    assert rx2.terminated == 0
    manager.tick(2, [dict(D1, address=15), D2])
    manager.tick(2.1)
    assert backend.preparations[-1][0]['address'] == 15
    backend.preparations[-1][1].code = 0
    manager.tick(2.2)
    assert manager.received(0, 3)
    assert rx2 is backend.radios[1][1]
    assert rx2.terminated == 0


def test_failed_rx_reinitializes_after_backoff_and_stop_cancels_retries():
    manager, backend = ready()
    backend.radios[0][1].code = 1
    manager.tick(1)
    assert manager.receivers[0]['connection'] == 'retrying'
    assert len(backend.preparations) == 2
    manager.tick(3)
    assert len(backend.preparations) == 3
    manager.close()
    manager.tick(100, [D1, D2])
    assert len(backend.preparations) == 3
    assert all(p.poll() is not None for _, p in backend.radios)


def test_absent_radio_waits_without_initializing_and_old_frames_are_ignored():
    backend = Backend()
    manager = RadioRecovery(backend)
    manager.tick(10, [])
    assert not backend.preparations
    assert not manager.received(0, 11)


def test_silent_rx_recovers_only_when_peer_receives_without_resetting_peer():
    manager, backend = ready()
    manager.received(0, 1)
    manager.received(1, 9.1)
    peer = backend.radios[1][1]
    manager.tick(9.2)
    assert backend.radios[0][1].terminated == 1
    assert peer.terminated == 0
    assert manager.receivers[0]['recovery_reason'] == 'silent_while_peer_receives'
    manager.tick(9.3)
    manager.tick(12)
    backend.preparations[-1][1].code = 0
    manager.tick(12.1)
    manager.received(1, 22)
    manager.tick(22)
    assert backend.radios[-1][1].terminated == 0  # cooldown, not a reset storm
    assert peer.terminated == 0


def test_out_of_range_on_both_receivers_does_not_reset_either():
    manager, backend = ready()
    manager.received(0, 1)
    manager.received(1, 1)
    for now in (4, 12, 80):
        manager.tick(now)
    assert all(process.terminated == 0 for _, process in backend.radios)
    assert all(item['connection'] == 'waiting' for item in manager.receivers)


def test_reconnection_with_new_address_keeps_restart_count():
    manager, backend = ready()
    manager.tick(1, [D2])
    manager.tick(2, [dict(D1, address=15), D2])
    manager.tick(2.1)
    backend.preparations[-1][1].code = 0
    manager.tick(2.2)
    assert manager.receivers[0]['restarts'] == 1
    assert manager.receivers[1]['restarts'] == 0


def test_first_retry_starts_within_half_second_without_resetting_peer():
    manager, backend = ready()
    peer = backend.radios[1][1]
    backend.radios[0][1].code = 1
    manager.tick(1)
    manager.tick(1.49)
    assert len(backend.preparations) == 2
    manager.tick(1.5)
    assert len(backend.preparations) == 3
    assert peer.terminated == 0


def test_disconnected_hung_process_does_not_hold_replug_for_three_seconds():
    manager, backend = ready()
    old = backend.radios[0][1]
    old.terminate = lambda: None  # USB teardown never completes.
    manager.tick(1, [D2])
    manager.tick(1.8, [dict(D1, address=15), D2])
    assert old.code == -9
    manager.tick(1.81)
    manager.tick(1.82)
    assert backend.preparations[-1][0]['address'] == 15
    assert backend.radios[1][1].terminated == 0
