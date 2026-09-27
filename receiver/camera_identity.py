"""Identify saved WFB peers from authenticated session and data packets.

The 17-byte forwarder header is not trusted as identity. Secret session material
stays in memory; only a saved profile ID is returned to the supervisor.
"""
from collections import OrderedDict
import struct

from nacl.bindings import crypto_aead_chacha20poly1305_decrypt
from nacl.exceptions import CryptoError
from nacl.public import Box, PrivateKey, PublicKey


class CameraIdentity:
    def __init__(self, store, link_id):
        self.channel_id = link_id << 8  # video stream 0
        self.boxes = []
        for profile in store.profiles():
            try:
                key = store.key_for(profile).read_bytes()
                self.boxes.append((profile['identity'], Box(PrivateKey(key[:32]), PublicKey(key[32:]))))
            except (OSError, ValueError, KeyError):
                continue
        self.sessions = OrderedDict()
        self.announcements = OrderedDict()
        self.last_data_check = -1.0

    def feed(self, packet, now):
        if len(packet) < 18 or packet[0] == 255:
            return None
        payload = packet[17:]
        if payload[0] == 2:
            if not 88 <= len(payload) <= 4096 or payload in self.announcements:
                return None
            self.announcements[payload] = True
            if len(self.announcements) > 32:
                self.announcements.popitem(last=False)
            matches = []
            for identity, box in self.boxes:
                try:
                    plain = box.decrypt(payload[25:], payload[1:25])
                except CryptoError:
                    continue
                if len(plain) < 47:
                    continue
                epoch, channel, fec, k, n = struct.unpack('!QIBBB', plain[:15])
                if channel == self.channel_id and fec == 1 and 1 <= k <= n:
                    matches.append((identity, plain[15:47]))
            # A shared/factory key cannot distinguish two saved cameras.
            if len(matches) == 1:
                identity, key = matches[0]
                self.sessions[key] = {'identity': identity, 'nonces': set(), 'first': now}
                if len(self.sessions) > 16:
                    self.sessions.popitem(last=False)
            return None
        if payload[0] != 1 or len(payload) < 28 or now - self.last_data_check < .05:
            return None
        self.last_data_check = now
        for key, session in self.sessions.items():
            nonce = payload[1:9]
            if nonce in session['nonces']:
                continue
            try:
                plain = crypto_aead_chacha20poly1305_decrypt(payload[9:], payload[:9], nonce, key)
            except CryptoError:
                continue
            if len(plain) < 3:
                continue
            session['nonces'].add(nonce)
            if len(session['nonces']) > 128:
                session['nonces'] = {nonce}
            if len(session['nonces']) >= 3:
                return session['identity']
        return None
