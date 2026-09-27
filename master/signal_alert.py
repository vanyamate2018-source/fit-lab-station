"""One loss announcement per outage, only after a received video stream."""
class SignalAlert:
    def __init__(self):
        self.armed = False
        self.missing_since = None
        self.announced = False
        self.recovered_since = None

    def update(self, state, running, now, suppress=False):
        if not running or suppress or state.get('phase') in ('idle', 'stopped', 'starting', 'searching'):
            self.__init__()
            return False
        receiving = (state.get('mbps') or 0) > 0.01
        if receiving:
            self.missing_since = None
            if state.get('phase') == 'video':
                self.armed = True
                if self.recovered_since is None:
                    self.recovered_since = now
                if now - self.recovered_since >= 3:
                    self.announced = False
            return False
        self.recovered_since = None
        if not self.armed or self.announced:
            return False
        if self.missing_since is None:
            self.missing_since = now
        if now - self.missing_since >= 3:
            self.announced = True
            return True
        return False
