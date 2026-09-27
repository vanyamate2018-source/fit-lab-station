"""Synchronize saved cameras with a receiver authenticated by its pinned SSH key."""
import subprocess
from pathlib import Path
from shared.binding_transfer import export_bindings


def sync_bindings(root, host, credentials=None):
    root = Path(root)
    command = ['ssh', '-T', '-i', str(root/'private/ssh/orangepi3b'),
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=3',
               'orangepi@' + host,
               'XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus PYTHONPATH=/mnt/fitlab-ssd/apps/fit-lab-station/runtime:/mnt/fitlab-ssd/apps/fit-lab-station/source '
               'python3 -m shared.binding_transfer /mnt/fitlab-ssd/apps/fit-lab-station/data']
    result = subprocess.run(command, input=export_bindings(root/'data', credentials),
                            capture_output=True, timeout=8)
    if result.returncode:
        raise RuntimeError('Не удалось передать сохранённые камеры приёмнику')
    return result.stdout.decode()
