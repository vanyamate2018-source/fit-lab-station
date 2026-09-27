"""Exercise the real camera receive, display decode, recording and RTSP paths.

Explicit bench invocation only; normal application reception has no timer.
"""
import json
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer
from master.session import StationSession


def main():
    os.environ.pop("FIT_LAB_TEST_LOSS", None)
    root = Path("/Volumes/FIT-LAB/data")
    app = QCoreApplication([])
    session = StationSession(root)
    started = time.monotonic()
    observed = {"frames": 0, "video_started": None, "stream_client_exit": None}
    client = None
    client_log = (root / "logs" / "rtsp-selftest.log").open("w")

    def frame(_):
        observed["frames"] += 1
    session.frame.connect(frame)
    session.message.connect(lambda value: print(value, flush=True))

    def tick():
        nonlocal client
        now = time.monotonic()
        state = session.state
        if state.get("phase") == "video" and observed["video_started"] is None:
            observed["video_started"] = now
            session.start_recording(root / "recordings")
            session.start_streaming("127.0.0.1")
        if state.get("streaming") == "streaming" and client is None:
            client = subprocess.Popen([
                "/opt/homebrew/bin/ffmpeg", "-hide_banner", "-loglevel", "info",
                "-rtsp_transport", "tcp", "-timeout", "10000000", "-i", state["stream_url"],
                "-t", "3", "-an", "-f", "null", "-"],
                stdin=subprocess.DEVNULL, stdout=client_log, stderr=subprocess.STDOUT)
        video_elapsed = now - observed["video_started"] if observed["video_started"] else 0
        if video_elapsed >= 15 or now - started > 100 or state.get("phase") == "error":
            timer.stop()
            observed["state_before_stop"] = dict(state)
            session.close()
            if client:
                try:
                    observed["stream_client_exit"] = client.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    client.terminate()
                    observed["stream_client_exit"] = client.wait(timeout=3)
            if session.record_path and session.record_path.exists():
                probe = subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "error", "-count_frames",
                    "-show_entries", "stream=codec_name,width,height,nb_read_frames:format=duration",
                    "-of", "json", str(session.record_path)], capture_output=True, text=True, timeout=15)
                observed["recording"] = str(session.record_path)
                observed["record_probe_exit"] = probe.returncode
                observed["record_probe"] = json.loads(probe.stdout) if probe.stdout else {}
            observed["elapsed_seconds"] = round(now - started, 2)
            observed["normal_duration_seconds"] = 0
            (root / "logs" / "media-integration-selftest.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2) + "\n")
            client_log.close()
            app.quit()
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(500)
    session.start("local", duration=0)
    app.exec()


if __name__ == "__main__":
    main()
