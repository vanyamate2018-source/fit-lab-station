"""Local RTP burst/loss/UI-stall test; never opens USB or contacts a camera."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

from PySide6.QtCore import QCoreApplication, QTimer
from master.session import StationSession


def main():
    root = Path(tempfile.mkdtemp(prefix="video-latency-", dir="/Volumes/FIT-LAB/data/temp"))
    for name in ("logs", "telemetry", "cache", "temp"):
        (root / name).mkdir()
    app = QCoreApplication([])
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(.005)
    stop = threading.Event()
    observed = {"synthetic": True, "camera_used": False, "dropped": 0, "frames": 0}
    first_frame = None
    final_state = {}
    samples = []
    session = StationSession(root)

    def frame(_):
        nonlocal first_frame
        if first_frame is None:
            first_frame = time.monotonic()
        observed["frames"] += 1

    def relay():
        batch = []
        flush = time.monotonic()
        while not stop.is_set():
            try:
                data, _ = receiver.recvfrom(65535)
                # Lose part of one GOP. The next IDR must restore decode.
                if first_frame and 3 < time.monotonic() - first_frame < 3.12:
                    observed["dropped"] += 1
                else:
                    batch.append(data)
            except socket.timeout:
                pass
            now = time.monotonic()
            if now - flush >= .035:
                for data in batch:
                    receiver.sendto(data, ("127.0.0.1", 5600))
                batch.clear()
                flush = now

    def sample(state):
        nonlocal final_state
        final_state = dict(state)
        if state.get("fps") is not None:
            samples.append({k: state.get(k) for k in ("phase", "fps", "pipeline_age_max_ms", "jitter_drop_events")})

    session.frame.connect(frame)
    session.changed.connect(sample)
    session.start("lan", latency=20, recovery="keyframe")
    if not session.running:
        receiver.close()
        session.close()
        raise RuntimeError("Test UDP port 5600 is unavailable")
    worker = threading.Thread(target=relay, daemon=True)
    worker.start()
    log = (root / "sender.log").open("wb")
    encoder = subprocess.Popen([
        "/opt/homebrew/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi",
        "-i", "testsrc2=size=640x360:rate=60", "-an", "-c:v", "libx265", "-preset", "ultrafast",
        "-tune", "zerolatency", "-x265-params", "log-level=error:keyint=30:min-keyint=30:scenecut=0:repeat-headers=1",
        "-f", "rtp", f"rtp://127.0.0.1:{receiver.getsockname()[1]}?pkt_size=1200"],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    began = time.monotonic()
    stalled = False

    def tick():
        nonlocal stalled
        elapsed = time.monotonic() - first_frame if first_frame else 0
        if elapsed > 6 and not stalled:
            stalled = True
            time.sleep(.25)  # Deliberately block only this test's UI loop.
        if elapsed > 10 or time.monotonic() - began > 20 or final_state.get("phase") == "error":
            timer.stop()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    try:
        app.exec()
        observed.update(ui_stall_tested=stalled, final_state=final_state, samples=samples, folder=str(root))
        assert observed["frames"] > 350 and observed["dropped"] > 0, observed["frames"]
        assert final_state.get("phase") == "video", final_state.get("phase")
        assert not final_state.get("jitter_drop_events", {}).get("drop-on-latency"), final_state.get("jitter_drop_events")
        assert final_state.get("pipeline_age_max_ms", 999) < 150, final_state.get("pipeline_age_max_ms")
        observed["passed"] = True
    finally:
        stop.set()
        worker.join(timeout=1)
        encoder.terminate()
        try:
            encoder.wait(timeout=4)
        except subprocess.TimeoutExpired:
            encoder.kill(); encoder.wait()
        receiver.close()
        log.close()
        session.close()
        (Path("/Volumes/FIT-LAB/data/exports/video-latency-selftest.json")).write_text(json.dumps(observed, indent=2))
    print(json.dumps({k: v for k, v in observed.items() if k not in ("samples", "final_state")}, indent=2))


if __name__ == "__main__":
    main()
