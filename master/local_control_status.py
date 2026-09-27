"""Read receiver control state without owning or stopping its service."""
import json
from shared.control_status import boot_identity, fresh_status


class LocalControlStatus:
    def __init__(self, data):
        self.path = data / 'logs/control-live.json'
        self.boot = boot_identity()

    def poll(self, now):
        try:
            value = json.loads(self.path.read_text())
            if value.get('owner') == 'service' and fresh_status(value, now, self.boot):
                return value
        except (OSError, ValueError, TypeError):
            pass
        return {'state': 'retrying'}

    def close(self, **kwargs):
        pass
