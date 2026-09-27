"""Save compressed RTP video and optional Opus independently of live playback."""
import argparse
import json
import os
import signal
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--audio-port", type=int, default=0)
    parser.add_argument("--codec", choices=("h264", "h265"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    pipeline = None
    running = True
    parent_pid = os.getppid()

    def event(**data):
        print(json.dumps(data, ensure_ascii=False), flush=True)

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        c = args.codec
        audio_branch = (
            f' udpsrc name=audio_source address=127.0.0.1 port={args.audio_port} '
            'buffer-size=65536 timeout=2000000000 '
            'caps="application/x-rtp,media=audio,encoding-name=OPUS,clock-rate=48000,payload=98" '
            '! rtpjitterbuffer latency=120 drop-on-latency=true do-lost=true '
            '! rtpopusdepay ! queue max-size-time=2000000000 '
            'max-size-bytes=0 max-size-buffers=0 ! mux.' if args.audio_port else '')
        pipeline = Gst.parse_launch(
            f'udpsrc address=127.0.0.1 port={args.port} buffer-size=1048576 '
            f'caps="application/x-rtp,media=video,encoding-name={c.upper()},clock-rate=90000" '
            f'! rtpjitterbuffer latency=120 drop-on-latency=false do-lost=true ! rtp{c}depay name=depay '
            f'! video/x-{c},alignment=au ! {c}parse name=parser config-interval=-1 ! queue max-size-time=2000000000 max-size-bytes=0 max-size-buffers=0 ! matroskamux name=mux ! filesink name=file sync=false' + audio_branch)
        depay = pipeline.get_by_name('depay')
        if depay.find_property('wait-for-keyframe') is not None:
            depay.set_property('wait-for-keyframe', True)
        waiting_for_keyframe = True
        def first_keyframe(pad, info):
            nonlocal waiting_for_keyframe
            buffer = info.get_buffer()
            if waiting_for_keyframe and buffer.has_flags(Gst.BufferFlags.DELTA_UNIT):
                return Gst.PadProbeReturn.DROP
            waiting_for_keyframe = False
            event(state="recording", path=args.output)
            return Gst.PadProbeReturn.REMOVE
        pipeline.get_by_name("parser").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, first_keyframe)
        pipeline.get_by_name("file").set_property("location", args.output)
        bus = pipeline.get_bus()
        event(state="starting", path=args.output)
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Не удалось начать запись")
        while running and os.getppid() == parent_pid:
            msg = bus.timed_pop_filtered(100 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS | Gst.MessageType.ELEMENT)
            if msg:
                if msg.type == Gst.MessageType.ELEMENT:
                    structure = msg.get_structure()
                    if structure and structure.get_name() == 'GstUDPSrcTimeout' and args.audio_port:
                        # End only the missing audio track; video keeps recording.
                        pipeline.get_by_name('audio_source').send_event(Gst.Event.new_eos())
                        event(state="audio_ended")
                    continue
                if msg.type == Gst.MessageType.ERROR:
                    error, _ = msg.parse_error()
                    raise RuntimeError(error.message)
                break
        pipeline.send_event(Gst.Event.new_eos())
        final = bus.timed_pop_filtered(3 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
        if final is None or final.type == Gst.MessageType.ERROR:
            raise RuntimeError("Запись не завершена: проверьте файл")
        if waiting_for_keyframe:
            raise RuntimeError("Нет видеокадров для сохранения")
        event(state="saved", path=args.output)
        return 0
    except Exception as exc:
        event(state="error", error=str(exc))
        return 1
    finally:
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    raise SystemExit(main())
