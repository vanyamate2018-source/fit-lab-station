"""TX failover must never restart a live peer or transmit through both paths."""
import socket
from types import SimpleNamespace

from receiver.control_link import ControlLink
from receiver.recovery import Job
from receiver.tx_diversity import TxDiversity


class Process:
    code = None

    def poll(self):
        return self.code


def job(index):
    return Job({}, index=index, process=Process(), phase='receiving')


def test_owner_is_sticky_and_switch_requires_confirmed_old_process_exit():
    first, second = job(0), job(1)
    states = [dict(last_frame_monotonic=10), dict(last_frame_monotonic=10)]
    policy = TxDiversity(observation_seconds=0)
    assert policy.select([first, second], states, 10.1) is first
    first.removing = True
    assert policy.select([first, second], states, 10.2) is None
    first.process.code = -9
    assert policy.select([second], states, 10.3) is second
    replacement = job(0)
    assert policy.select([replacement, second], states, 10.4) is second
    assert policy.switches == 1


def test_recovery_cannot_hide_still_running_old_transmitter():
    first, second = job(0), job(1)
    states = [dict(last_frame_monotonic=10), dict(last_frame_monotonic=10)]
    policy = TxDiversity(observation_seconds=0)
    assert policy.select([first, second], states, 10.1) is first
    old_process = first.process
    first.process, first.phase = Process(), 'preparing'
    assert policy.select([first, second], states, 10.2) is None
    old_process.code = 0
    assert policy.select([first, second], states, 10.3) is second


def test_no_owner_until_native_receiver_proves_ready_and_silence_does_not_flap():
    first, second = job(0), job(1)
    states = [dict(last_frame_monotonic=0), dict(last_frame_monotonic=0)]
    policy = TxDiversity(observation_seconds=0)
    assert policy.select([first, second], states, 10) is None
    states[1]['last_frame_monotonic'] = 10
    assert policy.select([first, second], states, 10.1) is second
    states[0]['last_frame_monotonic'] = 100
    assert policy.select([first, second], states, 100) is second
    assert policy.switches == 0


def test_initialized_bridge_can_send_recovery_commands_without_video():
    first = job(0)
    states = [dict(last_frame_monotonic=0)]
    policy = TxDiversity(observation_seconds=0)
    assert policy.select([first], states, 10) is None
    first.tx_ready = True
    assert policy.select([first], states, 10.1) is first


def test_real_udp_routes_to_one_bridge_and_discards_old_echo_on_failover():
    # Exercise the router with actual UDP sockets, without opening USB or keys.
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(3)]
    try:
        for sock in sockets:
            sock.bind(('127.0.0.1', 0))
            sock.settimeout(.05)
        first, second = job(0), job(1)
        first.tx_port, second.tx_port = [s.getsockname()[1] for s in sockets[1:]]
        recovery = SimpleNamespace(jobs={0: first, 1: second}, receivers=[
            dict(last_frame_monotonic=10), dict(last_frame_monotonic=10)])
        link = ControlLink.__new__(ControlLink)
        link.diversity, link.encoded, link.state = TxDiversity(observation_seconds=0), sockets[0], {}
        link.diversity_enabled = True
        link.tx_job = link.tx_process = None
        link.pending, link.last_reply, link.last_ping = {}, 0, 0
        link.select_receiver(recovery, 10.1)
        link.forward_encoded(b'first')
        assert sockets[1].recv(100) == b'first'
        try:
            sockets[2].recv(100)
            assert False, 'Standby bridge received a TX datagram'
        except TimeoutError:
            pass
        link.pending, link.last_reply = {1: 10.1}, 10.1
        first.process.code = 1
        link.select_receiver(recovery, 10.2)
        assert link.pending == {} and link.last_reply == 0
        assert link.state['tx_receiver'] == 2
        link.forward_encoded(b'second')
        assert sockets[2].recv(100) == b'second'
        assert second.process.poll() is None
        second.process.code = 1
        link.select_receiver(recovery, 10.3)
        link.forward_encoded(b'no-live-receiver')
        assert link.state['tx_dropped_no_receiver'] == 1
    finally:
        for sock in sockets:
            sock.close()


def test_initial_selection_uses_packet_quality_before_rssi_and_never_flaps():
    first, second = job(0), job(1)
    first.tx_ready = second.tx_ready = True
    states = [dict(last_frame_monotonic=10, packets_per_second=260, rssi_dbm=-15),
              dict(last_frame_monotonic=10, packets_per_second=600, rssi_dbm=-30)]
    policy = TxDiversity()
    assert policy.select([first, second], states, 10) is None
    assert policy.select([first, second], states, 11.5) is second
    states[0]['packets_per_second'] = 900
    assert policy.select([first, second], states, 12) is second
    assert policy.switches == 0


def test_no_video_still_allows_commands_after_bounded_initial_observation():
    first = job(0)
    first.tx_ready = True
    policy = TxDiversity()
    states = [dict(last_frame_monotonic=0)]
    assert policy.select([first], states, 10) is None
    assert policy.select([first], states, 11.5) is first
