"""Supervised LAN WFB aggregation; keys remain on the master."""
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
from shared.radio_telemetry import RadioTelemetry


class Antennas:
    def __init__(self):
        self.seen = {}
        self.tuning = {}

    def feed(self, line, now):
        match = re.search(r'\bRX_ANT\s+(\d+):\d+:(\d+)\s+([0-9a-f]+)\s+(\d+):(-?\d+):(-?\d+):(-?\d+):(\d+):(\d+):(\d+)', line)
        if not match:
            return
        index = (int(match[3], 16) >> 8) & 255
        if index not in (0, 1, 2):
            return
        frequency = int(match[1])
        from shared.radio_settings import CHANNELS, frequency as channel_frequency
        channel = next((c for c in CHANNELS if channel_frequency(c) == frequency), None)
        self.tuning = {'channel':channel, 'frequency_mhz': frequency, 'width': int(match[2])}
        antenna = int(match[3], 16) & 255
        self.seen[index, antenna] = (now, int(match[6]), int(match[4]), int(match[9]))

    def snapshot(self, now):
        result = []
        for index in range(max(2, max((rx + 1 for rx, _ in self.seen), default=0))):
            current = [v for (rx, _), v in self.seen.items() if rx == index and now-v[0] < 3]
            result.append({'index': index, 'connection': 'receiving' if current else 'waiting',
                           'rssi_dbm': max(v[1] for v in current) if current else None,
                           'snr_db': max(v[3] for v in current) if current else None, 'last_frame_monotonic': max(v[0] for v in current) if current else 0,
                           'source': 'lan', 'restarts': 0})
        return result


def main():
    root = Path(os.environ['FIT_LAB_ROOT'])
    data = Path(os.environ['FIT_LAB_DATA_ROOT'])
    embedded = os.environ.get('FIT_LAB_EMBEDDED_RECEIVER') == '1'
    binary = Path('/usr/local/libexec/fit-lab/wfb_rx') if embedded else root/'experiments/wfb-link/target/wfb-ng-macos/bin/wfb_rx'
    key = root/'private/runcam/gs.key'
    if not embedded and os.environ.get('FIT_LAB_FOLLOW_RECEIVER', '1') == '1':
        from master.receiver_camera import select_receiver_camera
        profile = select_receiver_camera(root, os.environ.get('FIT_LAB_RECEIVER_HOST', '192.168.2.36'))
        print('FITLAB_EVENT '+json.dumps({'selected_camera_profile': profile,
              'notice': 'Камера приёмника выбрана автоматически'}), flush=True)
    if not binary.is_file() or not key.is_file():
        raise RuntimeError('Не установлен компонент LAN-приёма или не выбрана камера')
    # Refuse an occupied port rather than running a competing aggregator.
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('0.0.0.0',15650))
    # Joining a running module must never overwrite its current RF channel.
    if os.environ.get('FIT_LAB_RETUNE') == '1':
        from shared.radio_settings import receiver_settings
        requested = receiver_settings(int(os.environ.get('FIT_LAB_RADIO_CHANNEL','40')),
                                      int(os.environ.get('FIT_LAB_RADIO_WIDTH','20')))
        retune = ['ssh','-T','-i',str(root/'private/ssh/orangepi3b'),'-o','IdentitiesOnly=yes',
                  '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=3',
                  'orangepi@'+os.environ.get('FIT_LAB_RECEIVER_HOST','192.168.2.36'),
                  'python3 /usr/local/libexec/fit-lab/command_bridge.py --tune %d %d' %
                  (requested['channel'], requested['width'])]
        if embedded:
            retune = ['python3', '/usr/local/libexec/fit-lab/command_bridge.py', '--tune', str(requested['channel']), str(requested['width'])]
        result = subprocess.run(retune, capture_output=True, timeout=6)
        if result.returncode:
            raise RuntimeError('LAN-модуль не принял настройку частоты')
    if embedded:
        from shared.receiver_outputs import update
        update(local_enabled=True)
    from shared.pairing_store import PairingStore
    active_profile = PairingStore(data).read(PairingStore(data).active_path) or {}
    from receiver.local_radio import free_aggregator_port
    from receiver.camera_fanout import CameraFanout
    aggregator_port = free_aggregator_port()
    fanout = CameraFanout(data, aggregator_port, '127.0.0.1' if embedded else os.environ.get('FIT_LAB_RECEIVER_HOST', '192.168.2.36'))
    try:
        child = subprocess.Popen([str(binary),'-a',str(aggregator_port),'-K',str(key),'-c','127.0.0.1',
                                  '-u',os.environ.get('FIT_LAB_RTP_PORT','5600'),'-i','7669206','-p','0'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception:
        fanout.close()
        if embedded:
            update(local_enabled=False)
        raise
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    poller = selectors.DefaultSelector()
    poller.register(child.stdout,selectors.EVENT_READ)
    antennas = Antennas()
    stats = RadioTelemetry(data/'logs/lan-wfb-aggregator.log')
    control = None
    control_state = {'state':'disabled'}
    if os.environ.get('FIT_LAB_CONTROL') == '1':
        try:
            if embedded:
                from master.local_control_status import LocalControlStatus
                control = LocalControlStatus(data)
            else:
                from master.remote_control import RemoteControl
                control = RemoteControl(root, os.environ.get('FIT_LAB_RECEIVER_HOST', '192.168.2.36'))
        except Exception as exc:
            control_state = {'state':'error', 'error':str(exc)}
    pending = b''
    last = 0
    parent = os.getppid()
    indicator_target = ('127.0.0.1' if embedded else os.environ.get('FIT_LAB_RECEIVER_HOST', '192.168.2.36'), 60401)
    from master.lan_indicators import LanIndicators
    indicators = LanIndicators(indicator_target)
    try:
        with stats.path.open('ab',buffering=0) as log:
            while not stopped and child.poll() is None and os.getppid() == parent:
                now=time.monotonic()
                for item,_ in poller.select(.01 if control is not None else .25):
                    chunk=os.read(item.fileobj.fileno(),65536)
                    if not chunk: break
                    log.write(chunk)
                    text=chunk.decode(errors='replace')
                    stats.feed(text,now)
                    pending+=chunk
                    lines=pending.split(b'\n');pending=lines.pop()[-8192:]
                    for line in lines: antennas.feed(line.decode(errors='replace'),now)
                if control is not None:
                    try: control_state = dict(control.poll(time.monotonic()))
                    except Exception as exc:
                        control_state = {'state':'error', 'error':str(exc)}
                if now-last>=1:
                    last=now
                    fresh=bool(stats.last_antenna and now-stats.last_antenna<3)
                    event={'state':'lan','observed_cameras':fanout.snapshot(now),'selected_camera':active_profile.get('identity'),'receivers':antennas.snapshot(now),'radio_tuning':antennas.tuning,
                           'radio':{'interval':dict(stats.latest) if fresh else {},'totals':dict(stats.totals),'antenna_fresh':fresh},
                           'control':control_state,'module_transport':'lan'}
                    if fresh and stats.latest.get('outgoing_packets', 0) > 0 and active_profile.get('identity'):
                        event.update(camera_identity=active_profile['identity'], camera_identity_monotonic=now)
                    indicators.update(event['receivers'])
                    print('FITLAB_EVENT '+json.dumps(event),flush=True)
    finally:
        fanout.close()
        if embedded:
            update(local_enabled=False)
        indicators.close()
        if control is not None: control.close()
        poller.close()
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:child.kill();child.wait()
    return 0 if stopped else (child.returncode or 1)

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('FITLAB_EVENT '+json.dumps({'state':'error','error':str(exc)}),flush=True)
        raise SystemExit(1)
