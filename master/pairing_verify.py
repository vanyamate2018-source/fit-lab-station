"""Run only inside the isolated pairing worker, with the normal RX stopped."""
from concurrent.futures import ThreadPoolExecutor
import os
import time
from PySide6.QtCore import QCoreApplication, QTimer
from master.session import StationSession


def verify_radio(root, ticket, host, username, password, radio, codec):
    from master.camera_api import connect_camera
    from master.camera_radio import command
    os.environ['FIT_LAB_PAIRING_ID'] = ticket
    app = QCoreApplication.instance() or QCoreApplication([])
    session = StationSession(root)
    pool = ThreadPoolExecutor(max_workers=1)
    probe = None
    frames = 0
    started = time.monotonic()
    result = {'passed': False, 'frames': 0}

    def frame(_):
        nonlocal frames
        frames += 1

    def check_identity():
        client = connect_camera(host, username, password, root, transport='radio')
        try:
            code, text = command(client, 'printf %s FITLAB_PAIR_' + ticket)
            return code == 0 and text == 'FITLAB_PAIR_' + ticket
        finally:
            client.close()

    def tick():
        nonlocal probe
        state = session.state
        live = state.get('phase') == 'video' and state.get('control', {}).get('state') == 'connected'
        if live and frames >= 90 and probe is None:
            probe = pool.submit(check_identity)
        if probe is not None and probe.done():
            try:
                result['passed'] = bool(probe.result()) and live
            except Exception as exc:
                result['error'] = 'Камера не подтвердила SSH по новой радиопривязке'
                result['failure_type'] = type(exc).__name__
            app.quit()
        elif time.monotonic() - started > 35 or state.get('phase') == 'error':
            result['error'] = 'Нет подтверждённого видео и ответа по новому ключу'
            app.quit()

    session.frame.connect(frame)
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    session.start('local', duration=0, latency=20, channel=radio['channel'], width=radio['width'],
                  codec=codec, control=True, decoder_mode='lowlatency')
    try:
        app.exec()
    finally:
        timer.stop()
        result.update(frames=frames, elapsed_seconds=round(time.monotonic()-started, 3),
                      fps=session.state.get('fps'), control=session.state.get('control'),
                      radio=session.state.get('radio'), size=[session.state.get('width'), session.state.get('height')])
        session.close()
        pool.shutdown(wait=True, cancel_futures=True)
        os.environ.pop('FIT_LAB_PAIRING_ID', None)
    return result
