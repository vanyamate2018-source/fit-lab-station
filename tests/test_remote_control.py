from master.remote_control import RemoteControl


def test_remote_control_never_reports_stale_confirmation():
    control=RemoteControl.__new__(RemoteControl)
    control.seen=10
    control.state={'state':'connected','rtt_ms':30,'last_reply_monotonic':500}
    assert control.poll(11)['last_reply_monotonic']==11
    assert control.poll(13)=={'state':'retrying'}
    control.state={'state':'waiting'}
    assert control.poll(11)=={'state':'waiting'}


def test_persisted_status_cannot_survive_receiver_reboot():
    from shared.control_status import fresh_status
    value={'updated':100,'boot_id':'old','state':'connected'}
    assert not fresh_status(value,1,'new')
    assert not fresh_status(value,99,'old')
    assert fresh_status(value,102,'old')
    assert not fresh_status(value,103,'old')
