"""Bench proof: parallel discovery, then wrong saved key -> automatic peer selection."""
import json
from pathlib import Path
import time

from PySide6.QtCore import QCoreApplication, QTimer, QProcess
from master.session import StationSession
from shared.pairing_store import PairingStore


def main():
    root = Path('/Volumes/FIT-LAB/data')
    store = PairingStore(root)
    original = store.read(store.active_path)
    other = next(p for p in store.profiles() if p['identity'] != original['identity'])
    app = QCoreApplication([])
    session = StationSession(root)
    began = time.monotonic()
    report = {'passed': False, 'camera_keys_changed': False, 'hardware': True, 'events': []}
    phase = 'discovery'
    frames = 0
    video_since = None
    def frame(_):
        nonlocal frames
        frames += 1
    session.frame.connect(frame)
    session.message.connect(lambda text: print(text, flush=True))
    session.cameraSelected.connect(lambda p: report['events'].append(dict(selected=p['identity'], seconds=round(time.monotonic()-began,3))))
    def tick():
        nonlocal phase, video_since
        now = time.monotonic()
        if phase == 'discovery' and any(c['identity'] == original['identity'] for c in session.discovered):
            report['discovery_seconds'] = round(now-began,3)
            report['discovered'] = session.discovered
            session.stop()
            phase = 'wait_stop'
        if phase == 'wait_stop' and session.scanner.state() == QProcess.ProcessState.NotRunning:
            store.select_known(other['identity'])
            profile = original['receiver_config']
            session.start(channel=profile['radio_channel'],width=profile['radio_width'],codec=profile['codec'].lower().replace('.',''),latency=20,control=True)
            phase = 'video'
        if phase == 'video' and frames and session.state.get('phase') == 'video':
            if video_since is None:
                video_since = now
                report['video_seconds'] = round(now-began,3)
            if now-video_since > 10:
                report['passed'] = store.read(store.active_path)['identity'] == original['identity'] and len(report['events'])==1
                report['final_state'] = dict(session.state)
                app.quit()
        if now-began > 85 or session.state.get('phase') == 'error':
            report['error'] = session.state.get('error','deadline')
            app.quit()
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    session.discover_cameras()
    try:
        app.exec()
    finally:
        timer.stop()
        session.close()
        store.select_known(original['identity'])
        report.update(frames=frames, elapsed_seconds=round(time.monotonic()-began,3))
        (root/'exports/camera-reconnect-20260926.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({k:v for k,v in report.items() if k not in ('final_state','discovered')},ensure_ascii=False),flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
