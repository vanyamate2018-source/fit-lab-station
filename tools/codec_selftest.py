"""Synthetic late-join/loss recording + RTSP test. Never opens USB or camera."""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from master.media_env import media_environment


def main():
    root = Path('/Volumes/FIT-LAB/data')
    folder = root / 'logs' / f'codec-bench-{time.time_ns()}'
    folder.mkdir()
    env = media_environment(root)
    sockets, processes, files = [], [], []

    def port(kind=socket.SOCK_DGRAM):
        sock = socket.socket(socket.AF_INET, kind)
        sock.bind(('127.0.0.1', 0))
        number = sock.getsockname()[1]
        sock.close()
        return number

    def run(args, name):
        stream = (folder / name).open('wb')
        files.append(stream)
        proc = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT)
        processes.append(proc)
        return proc

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(('127.0.0.1', 0))
    receiver.settimeout(.05)
    sockets.append(receiver)
    rec_port, relay_port, rtsp_port = port(), port(), port(socket.SOCK_STREAM)
    output = folder / 'synthetic-h265.mkv'
    packets = dropped = 0
    recorder = streamer = client = None
    try:
        sender = run(['/opt/homebrew/bin/ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-re', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30', '-an',
            '-c:v', 'libx265', '-preset', 'ultrafast', '-tune', 'zerolatency',
            '-x265-params', 'log-level=error:keyint=30:min-keyint=30:scenecut=0:repeat-headers=1',
            '-f', 'rtp', f'rtp://127.0.0.1:{receiver.getsockname()[1]}?pkt_size=1200'], 'sender.log')
        start = time.monotonic()
        while time.monotonic() - start < 13:
            elapsed = time.monotonic() - start
            if elapsed > .45 and recorder is None:
                recorder = run([sys.executable, '-m', 'master.record_worker', '--port', str(rec_port),
                                '--codec', 'h265', '--output', str(output)], 'record.log')
                streamer = run([sys.executable, '-m', 'master.stream_worker', '--host', '127.0.0.1',
                                '--input-port', str(relay_port), '--port', str(rtsp_port), '--codec', 'h265'], 'stream.log')
            if elapsed > 2 and client is None:
                client = run(['/opt/homebrew/bin/ffmpeg', '-hide_banner', '-loglevel', 'error',
                    '-rtsp_transport', 'tcp', '-timeout', '5000000', '-i', f'rtsp://127.0.0.1:{rtsp_port}/live',
                    '-t', '3', '-f', 'null', '-'], 'client.log')
            try:
                data, _ = receiver.recvfrom(65535)
            except socket.timeout:
                continue
            packets += 1
            # One loss burst mid-GOP: recording should recover at the next IDR.
            if 6.4 < elapsed < 6.55:
                dropped += 1
                continue
            if recorder:
                receiver.sendto(data, ('127.0.0.1', rec_port))
                receiver.sendto(data, ('127.0.0.1', relay_port))
        recorder.terminate()
        recorder.wait(timeout=6)
        client.wait(timeout=6)
        probe = subprocess.run(['/opt/homebrew/bin/ffprobe', '-v', 'error', '-count_frames',
            '-show_entries', 'stream=codec_name,width,height,nb_read_frames:format=duration', '-of', 'json', str(output)],
            capture_output=True, text=True, timeout=15)
        report = dict(synthetic=True, camera_used=False, packets=packets, dropped=dropped,
                      recorder_exit=recorder.returncode, client_exit=client.returncode,
                      probe_exit=probe.returncode, decode_error_lines=len(probe.stderr.splitlines()),
                      probe=json.loads(probe.stdout) if probe.stdout else {}, folder=str(folder))
        (folder / 'decode.log').write_text(probe.stderr)
        (root / 'logs/codec-selftest.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        return 0 if recorder.returncode == client.returncode == probe.returncode == 0 and not probe.stderr else 1
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for stream in files:
            stream.close()
        for sock in sockets:
            sock.close()


if __name__ == '__main__':
    raise SystemExit(main())
