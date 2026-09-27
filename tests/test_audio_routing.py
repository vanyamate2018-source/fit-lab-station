import struct
from master.rtp_relay import RtpRelay


def test_interleaved_opus_never_restarts_or_enters_video_decoder():
    def packet(pt, seq, ssrc):
        return struct.pack('!BBHII', 128, pt, seq, seq * 1500, ssrc) + b'payload'
    sent = []
    class Sender:
        def sendto(self, data, address):
            sent.append((data[1], address[1]))
    relay = RtpRelay()
    relay.configure(video=1000, audio=999, record=1001, stream=1002)
    for pt, seq, ssrc in ((97, 1, 10), (98, 400, 99), (97, 2, 10)):
        relay._route(Sender(), packet(pt, seq, ssrc), '127.0.0.1')
    state = relay.snapshot()
    assert state['audio_packets'] == 1
    assert state['packets'] == 2
    assert state['integrity']['source_restarts'] == 0
    assert state['integrity']['sequence_gaps'] == 0
    assert [port for pt, port in sent if pt == 98] == [999]
    assert [port for pt, port in sent if pt == 97] == [1000, 1001, 1002] * 2
