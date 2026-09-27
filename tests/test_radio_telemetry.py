import pytest

from receiver.dual_radio import loss_phase
from shared.radio_telemetry import RadioTelemetry
from shared.wire import WireProtocolError, decode_announcement, decode_heartbeat


def test_partial_statistics_are_counted_once(tmp_path):
    parser = RadioTelemetry(tmp_path / "radio.log")
    parser.feed("100 PKT 10:12000:0:1:9:8:", 10)
    assert parser.totals["incoming_packets"] == 0
    parser.feed("2:1:0:6:7000\n100 RX_ANT 5805:1:20 0000 10:-60:-50:-40:10:20:30\n", 11)
    assert parser.totals["incoming_packets"] == 10
    assert parser.totals["fec_recovered"] == 2
    assert parser.totals["lost_packets"] == 1
    assert parser.latest["rssi_dbm"] == -50
    parser.feed("malformed PKT 1:2:3\n", 12)
    assert parser.totals["incoming_packets"] == 10


@pytest.mark.parametrize("decoder", [decode_announcement, decode_heartbeat])
@pytest.mark.parametrize("payload", [b"[]", b"null", b"42", b'"text"'])
def test_non_object_datagrams_do_not_crash_discovery(decoder, payload):
    with pytest.raises(WireProtocolError):
        decoder(payload)


def test_loss_test_is_opt_in_and_keeps_alternate_receiver():
    assert loss_phase(999, False) == ("normal", (0, 0))
    assert loss_phase(14.999, True)[1] == (0, 0)
    assert loss_phase(15, True)[1] == (1, 0)
    assert loss_phase(30, True)[1] == (0, 1)
    assert loss_phase(45, True)[1] == (.15, .15)
