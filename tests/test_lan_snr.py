from master.lan_receiver import Antennas


def test_snr_per_receiver_and_expiration():
    stats = Antennas()
    stats.feed('100 RX_ANT 5180:1:20 7f00000100000000 50:-65:-60:-55:10:18:25', 1)
    stats.feed('100 RX_ANT 5180:1:20 7f00000100000100 50:-70:-64:-60:8:12:18', 1)
    assert [x['snr_db'] for x in stats.snapshot(2)] == [18, 12]
    assert [x['snr_db'] for x in stats.snapshot(5)] == [None, None]
