"""On-demand LAN browser relay: H.265/H.264 in, hardware H.264 WebRTC out.

Independent from the viewing/recording pipelines; never changes camera encoding.
MediaMTX API and publishing listener are loopback only, no cloud/STUN services.
"""
import argparse
import sys
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def relay_config(host, rtsp, api):
    from master.viewer_network import is_lan_address
    if not is_lan_address(host):
        raise ValueError("Нужен адрес локальной сети")
    return {"logLevel": "warn", "rtsp": True, "rtspAddress": f"127.0.0.1:{rtsp}",
            "rtspTransports": ["tcp"], "api": True, "apiAddress": f"127.0.0.1:{api}",
            "hls": False, "rtmp": False, "srt": False, "moq": False, "playback": False,
            "webrtc": True, "webrtcAddress": f"{host}:8889",
            "webrtcLocalUDPAddress": f"{host}:8189", "webrtcLocalTCPAddress": f"{host}:8189",
            "webrtcIPsFromInterfaces": False, "webrtcAdditionalHosts": [host], "webrtcICEServers2": [],
            "webrtcAllowOrigins": [f"http://{host}:8889", f"http://{host}:8890"],
            "authInternalUsers": [
                {"user": "any", "ips": ["127.0.0.1"], "permissions": [{"action": "publish", "path": "live"}, {"action": "api"}]},
                {"user": "any", "ips": [], "permissions": [{"action": "read", "path": "live"}]}],
            "paths": {"live": {"source": "publisher"}}}


def launch_pipeline(codec, port, rtsp):
    # A clean access unit after loss prevents forwarding corrupted reference
    # frames. Baseline H.264 without B frames works across WebRTC browsers.
    decoder = 'vtdec'
    encoder = 'vtenc_h264 realtime=true allow-frame-reordering=false bitrate=4000 max-keyframe-interval=30'
    depay_options = 'wait-for-keyframe=true request-keyframe=true'
    convert = 'videoconvert ! '
    if sys.platform == 'linux':
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst
        Gst.init(None)
        decoder = 'mppvideodec fast-mode=true'
        encoder = 'mpph264enc bps=4000000 gop=30 profile=baseline header-mode=each-idr'
        depay = Gst.ElementFactory.make(f'rtp{codec}depay')
        depay_options = ' '.join(name+'=true' for name in ('wait-for-keyframe','request-keyframe') if depay and depay.find_property(name))
        convert = ''
    return (f'udpsrc address=127.0.0.1 port={port} buffer-size=2097152 '
            f'caps="application/x-rtp,media=video,encoding-name={codec.upper()},clock-rate=90000" '
            f'! rtpjitterbuffer latency=80 drop-on-latency=false do-lost=true '
            f'! rtp{codec}depay {depay_options} '
            f'! {codec}parse ! video/x-{codec},alignment=au ! {decoder} '
            # Preserve encoded fragments; shed only complete decoded frames
            # if the optional web encoder falls behind the camera.
            '! queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream '
            f'! videorate drop-only=true ! {convert}video/x-raw,format=NV12,framerate=30/1 '
            '! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream '
            f'! {encoder} '
            '! h264parse config-interval=-1 ! video/x-h264,profile=baseline,alignment=au '
            f'! rtspclientsink protocols=tcp latency=0 location=rtsp://127.0.0.1:{rtsp}/live')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--input-port", type=int, required=True)
    parser.add_argument("--codec", choices=("h264", "h265"), required=True)
    parser.add_argument("--external-viewer", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ.get("FIT_LAB_DATA_ROOT", "/Volumes/FIT-LAB/data"))
    executable = root.parent / "tools/mediamtx/mediamtx"
    if not executable.is_file():
        raise ValueError("Модуль веб-трансляции не установлен")
    folder = Path(tempfile.mkdtemp(prefix="web-relay-", dir=root / "temp"))
    rtsp, api = free_port(), free_port()
    config = folder / "mediamtx.yml"
    config.write_text(json.dumps(relay_config(args.host, rtsp, api)))
    config.chmod(0o600)
    parent = os.getppid()
    server = pipeline = viewer = None
    try:
        with (root / "logs/web-relay.log").open("ab") as output:
            server = subprocess.Popen([str(executable), str(config)], stdout=output, stderr=output, stdin=subprocess.DEVNULL)
        def api_get(path):
            # Do not send local control through system proxies/VPN middleware.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{api}/v3/{path}", timeout=.5) as response:
                return json.load(response)
        for _ in range(30):
            if server.poll() is not None:
                raise ValueError("Порты веб-трансляции недоступны")
            try:
                api_get("paths/list")
                break
            except OSError:
                time.sleep(.1)
        else:
            raise ValueError("Веб-трансляция не подтвердила запуск")
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst, GLib
        Gst.init(None)
        pipeline = Gst.parse_launch(launch_pipeline(args.codec, args.input_port, rtsp))
        loop = GLib.MainLoop()
        errors = []
        def error(message):
            errors.append(message)
            loop.quit()
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        def message(_, event):
            if event.type == Gst.MessageType.ERROR:
                detail, _ = event.parse_error()
                error(str(detail))
        bus.connect("message", message)
        pipeline.set_state(Gst.State.PLAYING)
        from master.viewer_server import serve_viewer
        if not args.external_viewer:
            viewer = serve_viewer(args.host)
        published = False
        started = last_api = time.monotonic()
        previous_bytes = None
        last_data = started
        last_ready = None
        def observe():
            nonlocal published, last_api, previous_bytes, last_data, last_ready
            if os.getppid() != parent:
                loop.quit(); return False
            if server.poll() is not None:
                error("Веб-сервер завершил работу"); return False
            try:
                path = api_get("paths/get/live")
                now = time.monotonic()
                last_api = now
                received = path.get('bytesReceived', 0)
                if received != previous_bytes:
                    last_data = now
                    previous_bytes = received
                if path.get("ready"):
                    if not published:
                        print(json.dumps({"state": "streaming", "url": f"http://{args.host}:8890/", "codec": "h264", "fps_limit": 30}), flush=True)
                        published = True
                    print(json.dumps({"state": "clients", "count": len(path.get("readers", []))}), flush=True)
                ready = bool(path.get('ready')) and now - last_data < 3
                if ready != last_ready:
                    print(json.dumps({'state': 'signal', 'ready': ready}), flush=True)
                    last_ready = ready
            except OSError:
                pass
            if not published and time.monotonic() - started > 15:
                error('Нет видеоданных для трансляции · дождитесь изображения и повторите запуск'); return False
            if time.monotonic() - last_api > 5:
                error('Сервер трансляции не отвечает'); return False
            return True
        GLib.timeout_add(1000, observe)
        signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(loop.quit))
        signal.signal(signal.SIGINT, lambda *_: GLib.idle_add(loop.quit))
        loop.run()
        if errors:
            raise ValueError(errors[0])
    finally:
        if viewer is not None:
            viewer.shutdown()
            viewer.server_close()
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=4)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait()
        config.unlink(missing_ok=True)
        folder.rmdir()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"state": "error", "error": str(exc)}), flush=True)
        raise SystemExit(1)
