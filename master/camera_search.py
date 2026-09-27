"""Sticky camera selection and bounded search of saved radio channels."""
from shared.radio_settings import receiver_settings


def _tuning_pair(config):
    if not isinstance(config, dict):
        return None
    channel = config.get('channel', config.get('radio_channel'))
    width = config.get('width', config.get('radio_width', 20))
    try:
        receiver_settings(channel, width)
    except ValueError:
        return None
    return channel, width


class CameraSearch:
    def __init__(self, profiles, active, tuning, now):
        self.profiles = {p['identity']: p for p in profiles}
        self.active = active
        self.channels = []
        for config in [tuning] + [p.get('receiver_config', {}) for p in profiles]:
            pair = _tuning_pair(config)
            if pair is not None and pair not in self.channels:
                self.channels.append(pair)
        self.tuned(now)

    def tuned(self, now):
        self.since = now
        self.ready_since = None
        self.last_activity = now
        self.candidates = {}

    def heard(self, identity, now):
        if identity in self.profiles:
            self.candidates[identity] = now

    def next(self, now, tuning, ready, active_video=False, active_control=False, blocked=False):
        live = _tuning_pair(tuning)
        current = (live or _tuning_pair(self.profiles.get(self.active, {}).get('receiver_config'))
                   or (self.channels[0] if self.channels else None))
        if active_video:
            self.last_activity = now
            if live is not None and live not in self.channels:
                self.channels.insert(0, live)
        if ready and self.ready_since is None:
            self.ready_since = now
        # Never change a live connection, or interfere with a settings transaction.
        if blocked or not ready or now - self.last_activity < 6 or current is None:
            return None
        candidates = [identity for identity, stamp in self.candidates.items() if now - stamp < 1.5]
        if len(candidates) > 1:
            return None  # Do not let packet arrival order choose between cameras.
        if candidates:
            identity = candidates[0]
            if identity != self.active:
                action = {'identity': identity, 'channel': current[0], 'width': current[1]}
                if live is None:
                    action['tuning_verified'] = False
                return action
            # A matching camera with an encoder/FEC problem is not a reason to
            # abandon the channel where authenticated video packets are arriving.
            return None
        if active_control:
            return None  # Keep the verified control path; it cannot veto a different authenticated peer above.
        if len(self.channels) < 2 or now - self.last_activity < 12 or now - self.ready_since < 8:
            return None
        index = self.channels.index(current) if current in self.channels else -1
        channel, width = self.channels[(index + 1) % len(self.channels)]
        return {'channel': channel, 'width': width}


def available_cameras(cameras, now, max_age=5):
    """Use only fresh authenticated observations, deduplicated across both RXs."""
    return {item['identity']: item for item in cameras
            if 0 <= now - item.get('last_seen', 0) < max_age}
