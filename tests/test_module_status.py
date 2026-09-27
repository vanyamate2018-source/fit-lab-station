import pytest

from master.module_status import discovered_status, local_receiver_status
from shared.models import ModuleInfo, ModuleKind, ModuleState


def test_usb_presence_does_not_mean_radio_is_receiving():
    result = local_receiver_status([{}, {}], {}, False, 'local', now=100)
    assert result.usb_count == 2 and result.receiving_count == 0
    assert result.tone == 'warning' and result.video == 'Ожидание'


@pytest.mark.parametrize('running,mode,expected', [(True, 'local', 1), (False, 'local', 0), (True, 'lan', 0)])
def test_only_fresh_packets_from_current_local_session_count(running, mode, expected):
    state = {'phase': 'video', 'width': 1280, 'height': 720,
             'receivers': [{'last_frame_monotonic': 99}, {'last_frame_monotonic': 97}]}
    result = local_receiver_status([{}, {}], state, running, mode, now=100)
    assert result.receiving_count == expected
    assert result.tone != 'ready'


def test_discovery_cannot_claim_authenticated_readiness():
    module = ModuleInfo('rx', ModuleKind.RECEIVER, 'RX', 1, state=ModuleState.READY)
    assert discovered_status(module) == ('В сети · приём не подтверждён', 'warning', 'waiting')
    module.state = ModuleState.UNREACHABLE
    assert discovered_status(module)[0] == 'Нет связи'


def test_old_tx_response_cannot_appear_connected():
    state = {'control': {'state': 'connected', 'rtt_ms': 15, 'last_reply_monotonic': 90}}
    assert local_receiver_status([{}], state, True, 'local', now=100).tx == 'Нет ответа'
    state['control']['last_reply_monotonic'] = 99
    assert local_receiver_status([{}], state, True, 'local', now=100).tx == 'Ответ · 15 мс'
