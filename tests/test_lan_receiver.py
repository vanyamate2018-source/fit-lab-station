from master.lan_receiver import Antennas


def test_remote_antennas_are_grouped_by_receiver_and_expire():
    data = Antennas()
    data.feed('1 RX_ANT 5200:1:20 c0a8022400000101 650:-44:-40:-38:0:0:0',10)
    data.feed('1 RX_ANT 5200:1:20 c0a8022400000100 650:-49:-46:-41:0:0:0',10)
    data.feed('1 RX_ANT 5200:1:20 c0a8022400000000 620:-50:-48:-44:0:0:0',10)
    rx=data.snapshot(11)
    assert [r['rssi_dbm'] for r in rx]==[-48,-40]
    assert all(r['connection']=='receiving' for r in rx)
    assert all(r['snr_db'] == 0 for r in rx)  # Preserve the driver's reported value.
    assert all(r['connection']=='waiting' for r in data.snapshot(14))
    assert data.tuning=={'channel':40,'frequency_mhz':5200,'width':20}


def test_third_receiver_keeps_own_identity_and_expires():
    data = Antennas()
    data.feed('1 RX_ANT 5825:1:20 c0a8022400000200 600:-55:-50:-45:10:15:20', 10)
    rx = data.snapshot(11)
    assert len(rx) == 3
    assert rx[2]['index'] == 2 and rx[2]['rssi_dbm'] == -50
    assert rx[2]['snr_db'] == 15 and rx[2]['connection'] == 'receiving'
    assert all(r['connection'] == 'waiting' for r in rx[:2])
    assert data.snapshot(14)[2]['connection'] == 'waiting'
    data.feed('1 RX_ANT 5825:1:20 c0a8022400000300 600:-55:-50:-45:10:15:20', 14)
    assert len(data.snapshot(14)) == 3
