"""Resolve the receiver's active camera over pinned SSH before opening video."""
import json
import subprocess
from pathlib import Path
from shared.pairing_store import PairingStore


def select_receiver_camera(root, host):
    root = Path(root)
    result = subprocess.run([
        'ssh', '-T', '-i', str(root/'private/ssh/orangepi3b'),
        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=3',
        'orangepi@'+host,
        'cat /mnt/fitlab-ssd/apps/fit-lab-station/data/config/radio-binding.json'
    ], capture_output=True, timeout=5)
    if result.returncode or len(result.stdout) > 65536:
        raise ValueError('Не удалось подтвердить камеру приёмника')
    remote = json.loads(result.stdout)
    store = PairingStore(root/'data')
    known = next((p for p in store.profiles() if p['identity'] == remote.get('identity')), None)
    if not known or any(known.get(k) != remote.get(k) for k in ('gs_public','drone_public','ssh_fingerprint')):
        raise ValueError('Камера приёмника не совпадает с сохранённой привязкой')
    store.select_known(known['identity'])
    return known
