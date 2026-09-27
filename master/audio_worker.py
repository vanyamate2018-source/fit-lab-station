"""Independent Opus RTP playback; bounded buffers and no audio recording."""
import argparse
import json
import os
import select
import signal
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    Gst.init(None)
    sink = 'osxaudiosink' if sys.platform == 'darwin' else 'wasapisink' if sys.platform == 'win32' else 'pulsesink'
    pipeline = Gst.parse_launch(
        f'udpsrc address=127.0.0.1 port={args.port} buffer-size=65536 '
        'caps="application/x-rtp,media=audio,encoding-name=OPUS,clock-rate=48000,payload=98" '
        '! rtpjitterbuffer latency=60 drop-on-latency=true do-lost=true '
        '! rtpopusdepay ! opusdec plc=true ! audioconvert ! audioresample '
        '! identity name=decoded silent=true ! level name=meter interval=250000000 '
        '! queue max-size-buffers=4 max-size-time=80000000 max-size-bytes=0 leaky=downstream '
        f'! volume name=gain volume=0.35 ! {sink} sync=true')
    gain, decoded = pipeline.get_by_name('gain'), pipeline.get_by_name('decoded')
    running = True
    parent = os.getppid()
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    buffer = b''
    last = time.monotonic()
    peak = None
    previous = 0
    try:
        pipeline.set_state(Gst.State.PLAYING)
        bus = pipeline.get_bus()
        while running and os.getppid() == parent:
            if select.select([sys.stdin], [], [], 0)[0]:
                data = os.read(sys.stdin.fileno(), 4096)
                if not data:
                    break
                buffer += data
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        command = json.loads(line)
                        gain.set_property('volume', max(0., min(1., float(command['volume']))))
                        gain.set_property('mute', bool(command['muted']))
                    except (ValueError, KeyError, TypeError):
                        pass
                if len(buffer) > 4096:
                    break
            message = bus.timed_pop_filtered(50 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.ELEMENT)
            if message:
                if message.type == Gst.MessageType.ERROR:
                    error, _ = message.parse_error()
                    print(json.dumps({'state': 'error', 'domain': error.domain, 'code': error.code}), flush=True)
                    break
                structure = message.get_structure()
                if structure is not None and structure.get_name() == 'level':
                    peak = round(max(structure.get_value('peak')), 1)
            if time.monotonic() - last >= 1:
                count = int(decoded.get_property('stats').get_value('num-buffers'))
                print(json.dumps(dict(state='playing' if count > previous else 'waiting',
                    decoded_buffers=count, peak_db=peak, muted=gain.get_property('mute'))), flush=True)
                previous, last = count, time.monotonic()
    finally:
        pipeline.set_state(Gst.State.NULL)


if __name__ == '__main__':
    main()
