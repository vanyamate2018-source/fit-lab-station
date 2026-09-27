"""Transfer receiver-only camera credentials through an authenticated SSH pipe."""
import base64
import json
import re
from shared.pairing_store import PairingStore, atomic_write, public_fingerprint


def export_bindings(data, credentials=None):
    store = PairingStore(data)
    envelope = {'version': 1, 'profiles': [
        {'profile': p, 'key': base64.b64encode(store.key_for(p).read_bytes()).decode()}
        for p in store.profiles()]}
    if credentials is not None:
        for item in envelope['profiles']:
            # Only credentials authenticated for this exact camera, never the common fallback.
            saved = credentials._read('camera:' + item['profile']['ssh_fingerprint'])
            if saved:
                item['credentials'] = list(saved)
    return json.dumps(envelope).encode()


def import_bindings(data, payload, credentials=None):
    from nacl.public import PrivateKey
    import fcntl
    if len(payload) > 262144:
        raise ValueError('Transfer too large')
    envelope = json.loads(payload)
    if envelope.get('version') != 1 or len(envelope['profiles']) > 64:
        raise ValueError('Invalid transfer')
    store = PairingStore(data)
    validated = []
    for item in envelope['profiles']:
        p = item['profile']
        key = base64.b64decode(item['key'], validate=True)
        if (not re.fullmatch(r'[0-9a-f]{24}', p['identity']) or p['stage'] != 'committed'
                or p.get('archived') or p.get('revoked') or len(key) != 64):
            raise ValueError('Invalid camera profile')
        folder = store.folder(p['ticket'])
        if (public_fingerprint(bytes(PrivateKey(key[:32]).public_key)) != p['gs_public']
                or public_fingerprint(key[32:]) != p['drone_public']):
            raise ValueError('Profile key mismatch')
        login = item.get('credentials')
        if login is not None and (not isinstance(login, list) or len(login) != 2
                or not all(isinstance(v, str) and len(v) <= 2048 for v in login)):
            raise ValueError('Invalid credentials')
        validated.append((p, key, folder, login))
    store.config.mkdir(parents=True, exist_ok=True)
    with (store.config / '.pairing.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if store.pending():
            raise ValueError('Pairing in progress')
        destination = store.config / 'bindings'
        destination.mkdir(exist_ok=True)
        added = 0
        for p, key, folder, login in validated:
            target = destination / (p['identity'] + '.json')
            old = store.read(target)
            if old and (old.get('archived') or old.get('revoked')):
                continue
            if old and store.key_for(old).read_bytes() != key:
                raise ValueError('Camera key rotation requires coordinated activation')
            if login is not None:
                if credentials is None:
                    from master.camera_credentials import CameraCredentialStore
                    credentials = CameraCredentialStore(store.root)
                account = 'camera:' + p['ssh_fingerprint']
                saved_login = credentials._read(account)
                if saved_login and saved_login != tuple(login):
                    raise ValueError('Saved camera credentials differ; authenticate before replacement')
                if not saved_login:
                    credentials.durable_write(account, login)
            target = destination / (p['identity'] + '.json')
            # Local revocations and newer settings must never be overwritten.
            if target.exists():
                continue
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            folder.chmod(0o700)
            existing = folder / 'gs.key'
            if existing.exists() and existing.read_bytes() != key:
                raise ValueError('Conflicting stored key')
            atomic_write(existing, key)
            atomic_write(target, json.dumps(p).encode())
            added += 1
    import time
    atomic_write(store.config/'master-sync.json', json.dumps({
        'schema': 1, 'saved_at': time.time(), 'profiles': len(validated),
        'added': added, 'transport': 'ssh', 'active_session_unchanged': True
    }).encode())
    return added


if __name__ == '__main__':
    import sys
    print(json.dumps({'added': import_bindings(sys.argv[1], sys.stdin.buffer.read(262145))}))
