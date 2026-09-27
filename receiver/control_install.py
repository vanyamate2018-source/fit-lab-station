"""Install the per-user control service, with no elevated privileges."""
import os
from pathlib import Path
import subprocess


def quoted(value):
    return '"' + str(value).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"') + '"'


def install(root):
    root = Path(root).resolve()
    unit = Path.home() / '.config/systemd/user/fit-lab-control.service'
    content = '\n'.join([
        '[Unit]', 'Description=FIT-LAB radio control', 'StartLimitIntervalSec=0',
        '[Service]', 'Type=simple', 'UMask=0077',
        'Environment=' + quoted('FIT_LAB_ROOT=' + str(root)),
        'Environment=' + quoted('FIT_LAB_DATA_ROOT=' + str(root / 'data')),
        'Environment=FIT_LAB_EMBEDDED_RECEIVER=1',
        'Environment=' + quoted('PYTHONPATH=' + str(root / 'runtime') + ':' + str(root / 'source')),
        'Environment=' + quoted('PYTHONPYCACHEPREFIX=' + str(root / 'data/cache/python')),
        'ExecStart=/usr/bin/python3 -m receiver.control_service',
        'Restart=always', 'RestartSec=3', 'TimeoutStopSec=10',
        '[Install]', 'WantedBy=default.target', ''])
    unit.parent.mkdir(parents=True, exist_ok=True)
    if not unit.exists() or unit.read_text() != content:
        unit.write_text(content)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=5)
    subprocess.run(['systemctl', '--user', 'enable', '--now', unit.name], check=True, timeout=8)


if __name__ == '__main__':
    install(os.environ['FIT_LAB_ROOT'])
