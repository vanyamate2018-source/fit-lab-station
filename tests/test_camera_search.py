import json
import struct
import pytest

from nacl.bindings import crypto_aead_chacha20poly1305_encrypt
from nacl.public import Box, PrivateKey, PublicKey

from master.camera_search import CameraSearch
from receiver.camera_identity import CameraIdentity
from shared.pairing_store import PairingStore


def bound(store, identity, channel):
    receipt = store.create(identity, '192.168.1.10', 'fingerprint-' + identity)
    receipt['receiver_config'] = dict(radio_channel=channel, radio_width=20, codec='H.265')
    store.activate(receipt)
    store.finish(receipt, True)
    return receipt


def packets(store, profile, session_key=b's'*32, channel_id=7669206 << 8):
    key = (store.folder(profile['ticket'])/'drone.key').read_bytes()
    box = Box(PrivateKey(key[:32]), PublicKey(key[32:]))
    nonce = b'n'*24
    plain = struct.pack('!QIBBB', 0, channel_id, 1, 8, 12) + session_key
    header = bytes(17)
    session = header + b'\x02' + nonce + box.encrypt(plain, nonce).ciphertext
    data = []
    for i in range(1, 8):
        nonce = i.to_bytes(8, 'big')
        ad = b'\x01' + nonce
        data.append(header + ad + crypto_aead_chacha20poly1305_encrypt(b'\x00\x00\x04test', ad, nonce, session_key))
    return session, data


def test_two_saved_peers_require_authentication_and_distinct_data(tmp_path):
    store = PairingStore(tmp_path/'data')
    a, b = bound(store, 'a'*24, 40), bound(store, 'b'*24, 161)
    detector = CameraIdentity(store, 7669206)
    session, data = packets(store, a)
    assert detector.feed(session, 1) is None
    assert detector.feed(session, 1.1) is None  # Session alone is insufficient.
    assert detector.feed(data[0], 1.2) is None
    assert detector.feed(data[0], 1.3) is None  # Duplicate from RX2 is not proof.
    assert detector.feed(data[1], 1.4) is None
    assert detector.feed(data[2], 1.5) == a['identity']
    session, data = packets(store, b, b't'*32)
    detector.feed(session, 2)
    for i, packet in enumerate(data[:3]):
        identity = detector.feed(packet, 2.1 + i*.1)
    assert identity == b['identity']
    assert detector.feed(data[3][:-1]+b'!', 3) is None
    assert detector.feed(b'bad', 4) is None


def test_wrong_stream_and_shared_factory_key_do_not_identify_camera(tmp_path):
    store = PairingStore(tmp_path/'data')
    a = bound(store, 'a'*24, 40)
    detector = CameraIdentity(store, 7669206)
    session, data = packets(store, a, channel_id=(7669206 << 8) + 32)
    detector.feed(session, 1)
    assert all(detector.feed(p, 2+i*.1) is None for i,p in enumerate(data))
    b = {**a, 'identity':'b'*24}
    (store.config/'bindings'/('b'*24+'.json')).write_text(json.dumps(b))
    detector = CameraIdentity(store, 7669206)
    session, data = packets(store, a)
    detector.feed(session, 1)
    assert all(detector.feed(p, 2+i*.1) is None for i,p in enumerate(data))


def test_selecting_known_camera_restores_its_key_without_generating(tmp_path):
    store = PairingStore(tmp_path/'data')
    (store.root/'logs').mkdir(parents=True)
    a, b = bound(store, 'a'*24, 40), bound(store, 'b'*24, 161)
    count = len(list(store.private.iterdir()))
    for profile in (a,b,a):
        store.select_known(profile['identity'])
        assert store.active_key.read_bytes() == store.key_for(profile).read_bytes()
        assert store.read(store.active_path)['identity'] == profile['identity']
    assert len(list(store.private.iterdir())) == count
    assert not (store.config/'pending-selection.json').exists()


def test_active_video_is_sticky_but_new_peer_wins_after_loss():
    profiles = [dict(identity='a', receiver_config=dict(radio_channel=40, radio_width=20)),
                dict(identity='b', receiver_config=dict(radio_channel=161, radio_width=20))]
    search = CameraSearch(profiles, 'a', dict(channel=40,width=20), 0)
    tuning = dict(channel=40,width=20)
    for now in range(1,30):
        search.heard('b', now)
        assert search.next(now,tuning,True,active_video=True) is None
    for now in range(30,35):
        search.heard('b', now)
        assert search.next(now,tuning,True) is None
    search.heard('b', 36)
    assert search.next(36,tuning,True,blocked=True) is None
    assert search.next(36,tuning,True)['identity'] == 'b'


def test_channel_scan_waits_for_adapter_and_does_not_loop_one_channel():
    profiles = [dict(identity='b', receiver_config=dict(radio_channel=161, radio_width=20))]
    tuning = dict(channel=40,width=20)
    search = CameraSearch(profiles, 'a', tuning, 0)
    assert search.next(100,tuning,False) is None
    assert search.next(101,tuning,True) is None
    assert search.next(110,tuning,True) == dict(channel=161,width=20)
    search = CameraSearch(profiles,'b',dict(channel=161,width=20),0)
    assert search.next(100,dict(channel=161,width=20),True) is None
    assert search.next(200,dict(channel=161,width=20),True) is None


def test_control_reply_cannot_hide_a_different_authenticated_camera():
    profiles = [dict(identity=i, receiver_config=dict(radio_channel=36, radio_width=20)) for i in ('a', 'b')]
    tuning = dict(channel=36, width=20)
    search = CameraSearch(profiles, 'a', tuning, 0)
    search.heard('b', 10)
    assert search.next(10, tuning, True, active_control=True)['identity'] == 'b'
    assert search.next(10, tuning, True, active_video=True, active_control=True) is None


def test_multiple_cameras_are_not_chosen_by_packet_arrival_order():
    profiles = [dict(identity=i, receiver_config=dict(radio_channel=36, radio_width=20)) for i in ('a', 'b', 'c')]
    tuning = dict(channel=36, width=20)
    search = CameraSearch(profiles, 'a', tuning, 0)
    search.heard('b', 10)
    search.heard('c', 10.1)
    assert search.next(10.2, tuning, True) is None
    search.heard('c', 12)
    assert search.next(12, tuning, True)['identity'] == 'c'


def test_available_cameras_require_fresh_proof_and_deduplicate_rx():
    from master.camera_search import available_cameras
    cameras = [dict(identity='a', last_seen=9), dict(identity='a', last_seen=10),
               dict(identity='stale', last_seen=1), dict(identity='future', last_seen=12)]
    assert available_cameras(cameras, 11) == {'a': cameras[1]}


@pytest.mark.parametrize('tuning', [None, {}, {'channel': None, 'width': 20}, {'channel': 36, 'width': None}])
def test_missing_live_tuning_uses_active_profile_for_key_handover(tuning):
    profiles = [dict(identity='a', receiver_config=dict(radio_channel=40, radio_width=20)),
                dict(identity='b', receiver_config=dict(radio_channel=161, radio_width=20))]
    search = CameraSearch(profiles, 'a', tuning, 0)
    search.heard('b', 5)
    assert search.next(5, tuning, True) is None
    search.heard('b', 7)
    assert search.next(7, tuning, True) == dict(identity='b', channel=40, width=20, tuning_verified=False)


def test_missing_tuning_scan_preserves_adapter_wait_and_channel_fallback():
    profiles = [dict(identity='b', receiver_config=dict(radio_channel=161, radio_width=20))]
    search = CameraSearch(profiles, 'unknown', dict(channel=40, width=20), 0)
    assert search.next(100, None, False) is None
    assert search.next(101, {}, True) is None
    assert search.next(110, None, True) == dict(channel=161, width=20)
    search.heard('b', 111)
    assert search.next(111, None, True) == dict(identity='b', channel=40, width=20, tuning_verified=False)


def test_valid_live_tuning_wins_over_saved_profile_and_empty_search_is_safe():
    profiles = [dict(identity=i, receiver_config=dict(radio_channel=40, radio_width=20)) for i in ('a', 'b')]
    search = CameraSearch(profiles, 'a', None, 0)
    search.heard('b', 7)
    assert search.next(7, dict(channel=161, width=40), True) == dict(identity='b', channel=161, width=40)
    empty = CameraSearch([], None, None, 0)
    assert empty.next(100, None, True, active_video=True) is None
    assert empty.next(120, {}, True) is None
