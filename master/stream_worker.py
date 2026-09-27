"""LAN-only RTSP relay; preserves the original compressed codec."""
import argparse
import json
import os
import signal


def main():
    parent_pid = os.getppid()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--input-port", type=int, required=True)
    parser.add_argument("--port", type=int, default=8554)
    parser.add_argument("--codec", choices=("h264", "h265"), required=True)
    args = parser.parse_args()
    import gi
    gi.require_version("Gst", "1.0")
    gi.require_version("GstRtspServer", "1.0")
    gi.require_version("GstRtsp", "1.0")
    from gi.repository import Gst, GstRtspServer, GstRtsp, GLib
    Gst.init(None)
    server = GstRtspServer.RTSPServer.new()
    server.set_address(args.host)
    server.set_service(str(args.port))
    factory = GstRtspServer.RTSPMediaFactory.new()
    # LAN datagram loss damaged reference frames in external players. Carry
    # RTP interleaved over TCP and repeat decoder headers on every keyframe.
    factory.set_protocols(GstRtsp.RTSPLowerTrans.TCP)
    c = args.codec
    factory.set_launch(
        f'( udpsrc address=127.0.0.1 port={args.input_port} buffer-size=1048576 '
        f'caps="application/x-rtp,media=video,encoding-name={c.upper()},clock-rate=90000" '
        f'! rtpjitterbuffer latency=80 drop-on-latency=false do-lost=true '
        f'! rtp{c}depay wait-for-keyframe=true request-keyframe=true '
        f'! {c}parse ! video/x-{c},alignment=au '
        f'! rtp{c}pay name=pay0 pt=96 config-interval=-1 )')
    factory.set_shared(True)
    server.get_mount_points().add_factory("/live", factory)
    if server.attach(None) == 0:
        raise RuntimeError("Адрес или порт трансляции недоступен")
    clients = set()
    def client_closed(client):
        clients.discard(client)
        print(json.dumps({"state": "clients", "count": len(clients)}), flush=True)
    def client_connected(server, client):
        clients.add(client)
        client.connect("closed", client_closed)
        print(json.dumps({"state": "clients", "count": len(clients)}), flush=True)
    server.connect("client-connected", client_connected)
    loop = GLib.MainLoop()
    def parent_alive():
        if os.getppid() != parent_pid:
            loop.quit()
            return False
        return True
    GLib.timeout_add(1000, parent_alive)
    signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(loop.quit))
    signal.signal(signal.SIGINT, lambda *_: GLib.idle_add(loop.quit))
    print(json.dumps({"state": "streaming", "url": f"rtsp://{args.host}:{args.port}/live"}), flush=True)
    loop.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"state": "error", "error": str(exc)}), flush=True)
        raise SystemExit(1)
