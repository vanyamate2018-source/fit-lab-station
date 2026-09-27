"""Explicit hardware bench check. No camera settings or keys are modified.

Uses the real StationSession and GStreamer decoder without creating a window.
Optional faults stop a verified native child, not a physical USB device.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import time

from PySide6.QtCore import QCoreApplication, QTimer
from master.session import StationSession
from receiver import local_radio as base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inject-process-faults', action='store_true')
    parser.add_argument('--hold-seconds', type=int, default=15)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not 15 <= args.hold_seconds <= 600:
        parser.error('hold-seconds must be between 15 and 600')
    os.environ['FIT_LAB_TX_DIVERSITY'] = '1'
    root = Path('/Volumes/FIT-LAB/data')
    prefs = json.loads((root / 'config/interface.json').read_text())
    app = QCoreApplication([])
    session = StationSession(root)
    began = time.monotonic()
    frames = 0
    stage_started = None
    rows, faults, recoveries = [], [], []
    result = dict(test='real_radio_headless', camera_settings_changed=False,
                  keys_changed=False, physical_usb_test=False, passed=False)

    def frame(_):
        nonlocal frames
        frames += 1

    def sample(state):
        rows.append(dict(time=time.monotonic(), frames=frames, **state))

    def tick():
        nonlocal stage_started
        now = time.monotonic()
        state = session.state
        control = state.get('control', {})
        receivers = state.get('receivers', [])
        ready = (state.get('phase') == 'video' and control.get('state') == 'connected'
                 and control.get('tx_receiver') in (1, 2)
                 and len(receivers) == 2 and all(r.get('connection') == 'receiving' for r in receivers))
        if stage_started is None and ready:
            stage_started = now
        if faults and len(recoveries) < len(faults):
            fault = faults[-1]
            if state.get('phase') == 'video' and control.get('state') == 'connected' and control.get('tx_receiver') == fault['peer']:
                peer = receivers[fault['peer'] - 1]
                recoveries.append(dict(seconds=round(now-fault['time'], 3),
                    tx_receiver=control['tx_receiver'], frames_since_fault=frames-fault['frames'],
                    peer_restarts=peer.get('restarts', 0)-fault['peer_restarts'],
                    decoder_restarts=state.get('decoder_restarts', 0)-fault['decoder_restarts']))
                print(json.dumps({'recovered': recoveries[-1]}), flush=True)
                stage_started = now
        fault_target_count = 2 if args.inject_process_faults else 0
        if (ready and stage_started is not None and now-stage_started >= 12
                and len(faults) < fault_target_count and len(faults) == len(recoveries)):
            owner = control['tx_receiver']
            rx, peer = receivers[owner-1], receivers[2-owner]
            pid = int(rx['process_id'])
            # Restrict injection to this session's native USB process.
            info = subprocess.check_output(['/bin/ps', '-p', str(pid), '-o', 'ppid=,comm='], text=True).strip().split(None, 1)
            if int(info[0]) != session.radio.processId() or info[1] != str(base.DIAG):
                result['error'] = 'Native process identity did not match'
                app.quit()
                return
            faults.append(dict(time=now, receiver=owner, peer=3-owner, process_id=pid,
                frames=frames, peer_restarts=peer.get('restarts', 0),
                decoder_restarts=state.get('decoder_restarts', 0)))
            print(json.dumps({'injecting_process_stop': owner, 'pid': pid}), flush=True)
            os.kill(pid, signal.SIGTERM)
            stage_started = None
        if (ready and stage_started is not None and now-stage_started >= args.hold_seconds
                and len(recoveries) == fault_target_count):
            result['passed'] = all(r['frames_since_fault'] > 0 and r['peer_restarts'] == 0
                                   and r['decoder_restarts'] == 0 for r in recoveries)
            app.quit()
        elif now-began > 90 + args.hold_seconds or (now-began > 35 and not frames) or state.get('phase') == 'error':
            result['error'] = state.get('error') or 'No complete radio/video/control verification before deadline'
            app.quit()

    session.frame.connect(frame)
    session.changed.connect(sample)
    session.message.connect(lambda value: print(value, flush=True))
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    session.start('local', duration=0, latency=prefs.get('latency', 20),
                  channel=prefs.get('radio_channel', 161), width=prefs.get('radio_width', 20),
                  codec=prefs.get('codec', 'H.265').lower().replace('.', ''),
                  recovery=prefs.get('recovery_mode', 'keyframe'), control=True,
                  decoder_mode=prefs.get('decoder_mode', 'lowlatency'))
    try:
        app.exec()
    finally:
        timer.stop()
        result.update(frames=frames, elapsed_seconds=round(time.monotonic()-began, 3),
                      faults=faults, recoveries=recoveries, final_state=dict(session.state))
        session.close()
        valid = [r for r in rows if r.get('phase') == 'video']
        result['fps_median'] = statistics.median(r.get('fps', 0) for r in valid) if valid else None
        result['samples'] = rows
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({k: v for k, v in result.items() if k not in ('samples', 'final_state')}, ensure_ascii=False, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
