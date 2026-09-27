"""Own only the FIT-LAB spectator AP; EOF tears it down after UI termination."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

PROFILE = 'FIT-LAB WFB'
HELPER = Path('/usr/local/sbin/fitlab-hotspot')


def helper(action):
    result = subprocess.run(['sudo', '-n', str(HELPER), action], capture_output=True,
                            text=True, timeout=60, env=dict(os.environ, LC_ALL='C'))
    if result.returncode:
        raise RuntimeError('Wi-Fi: ' + (result.stderr or result.stdout).strip()[:250])


def nm(*args):
    result = subprocess.run(['nmcli', '--wait', '12', *args], capture_output=True, text=True, timeout=16,
                            env=dict(os.environ, LC_ALL='C'))
    if result.returncode:
        raise RuntimeError('NetworkManager: ' + result.stderr.strip()[:250])
    return result.stdout.strip()


def start():
    # A preconfigured, dedicated AP profile is required. Never alter ordinary Wi-Fi.
    mode = nm('-g', '802-11-wireless.mode', 'connection', 'show', PROFILE)
    if mode != 'ap':
        raise RuntimeError('Сначала настройте сеть FIT-LAB WFB')
    nm('connection', 'modify', PROFILE, 'connection.autoconnect', 'no')
    if HELPER.is_file():
        helper('start')
    else:
        nm('connection', 'up', PROFILE)
    device = nm('-g', 'GENERAL.DEVICES', 'connection', 'show', PROFILE).splitlines()[0]
    address = nm('-g', 'IP4.ADDRESS', 'device', 'show', device).splitlines()[0].split('/')[0]
    from ipaddress import IPv4Address
    IPv4Address(address)
    return address


def stop():
    if HELPER.is_file():
        helper('stop')
        return
    active = nm('-g', 'NAME', 'connection', 'show', '--active').splitlines()
    if PROFILE in active:
        mode = nm('-g', '802-11-wireless.mode', 'connection', 'show', PROFILE)
        if mode != 'ap': raise RuntimeError('Профиль FIT-LAB WFB больше не является точкой доступа')
        device = nm('-g', 'GENERAL.DEVICES', 'connection', 'show', PROFILE).splitlines()[0]
        # Explicitly disconnect the owned AP device. Merely bringing the
        # profile down makes NM repeatedly try unrelated saved Wi-Fi networks.
        nm('device', 'disconnect', device)


def emit(**data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def main():
    if sys.platform != 'linux':
        emit(state='error', error='Автораздача требует системного модуля macOS')
        return 1
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ)
    quitting = False
    def quit(*_):
        nonlocal quitting
        quitting = True
    signal.signal(signal.SIGTERM, quit)
    signal.signal(signal.SIGINT, quit)
    owned = False
    parent = os.getppid()
    try:
        while not quitting and os.getppid() == parent:
            if not selector.select(.25): continue
            command = sys.stdin.readline().strip()
            if command == 'start':
                owned = True  # Also clean up if activation fails partway through.
                try: emit(state='ready', address=start())
                except Exception as exc:
                    emit(state='error', error=str(exc)); break
            elif command in ('stop', ''):
                break
    finally:
        if owned:
            try: stop(); emit(state='stopped')
            except Exception as exc: emit(state='error', error='Не удалось выключить Wi-Fi: '+str(exc))
        selector.close()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
