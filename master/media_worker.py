"""Isolated GStreamer decoder; bounded RGB frames go to Qt over a private pipe."""
from __future__ import annotations

import argparse
import json
import os
import signal
import struct
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--latency", type=int, default=40)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--codec", choices=("h264", "h265"), default="h265")
    parser.add_argument("--recovery", choices=("realtime", "keyframe"), default="keyframe")
    parser.add_argument("--frame-timestamps", action="store_true")
    parser.add_argument("--frame-memory")
    parser.add_argument('--window-handle', type=int, default=0)
    parser.add_argument('--window-width', type=int, default=640)
    parser.add_argument('--window-height', type=int, default=360)
    parser.add_argument('--decoder-mode', choices=('lowlatency', 'hardware'), default='lowlatency')
    args = parser.parse_args()
    if args.window_handle:
        os.environ['GST_GL_PLATFORM'] = 'egl'
        os.environ['GST_GL_API'] = 'gles2'
    # Native codecs can print startup diagnostics to fd 1. Keep the binary
    # frame transport on its own duplicated descriptor before loading them.
    frame_output = os.fdopen(os.dup(sys.stdout.fileno()), 'wb')
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    pipeline = None
    memory = None
    converter = None
    running = True
    parent_pid = os.getppid()
    from pathlib import Path
    from shared.media_activity import MediaActivity
    activity = MediaActivity(Path(os.environ.get("FIT_LAB_DATA_ROOT", "/Volumes/FIT-LAB/data")))
    activity.start()

    def stop(*_):
        nonlocal running
        running = False

    def event(**data):
        print(json.dumps(data, ensure_ascii=False), file=sys.stderr, flush=True)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        import gi
        gi.require_version("Gst", "1.0")
        gi.require_version("GstVideo", "1.0")
        from gi.repository import Gst, GstVideo
        if args.frame_memory:
            from multiprocessing.shared_memory import SharedMemory
            if sys.version_info >= (3, 13):
                memory = SharedMemory(name=args.frame_memory, track=False)
            else:
                memory = SharedMemory(name=args.frame_memory)
                # This independent worker attaches; only the Qt owner unlinks.
                from multiprocessing import resource_tracker
                resource_tracker.unregister(memory._name, 'shared_memory')
            os.set_blocking(sys.stdin.fileno(), False)
        Gst.init(None)
        codec = args.codec
        # vtdec 1.28 keeps 16 HEVC frames for presentation reordering even on
        # this camera's I/P stream (533 ms at 30 fps). Slice-only libav avoids
        # both that queue and frame-thread latency. Keep HW mode selectable.
        decoder = "vtdec" if args.decoder_mode == 'hardware' and sys.platform == "darwin" and Gst.ElementFactory.find("vtdec") else f"avdec_{codec}"
        if sys.platform == 'linux' and args.decoder_mode == 'hardware' and Gst.ElementFactory.find('mppvideodec'):
            decoder = 'mppvideodec'
        decode_element = decoder + ((' max-threads=4 thread-type=slice' if sys.platform == 'linux' else ' max-threads=1 thread-type=slice') if decoder.startswith('avdec_') else ' fast-mode=true' if decoder == 'mppvideodec' else '')
        depay = Gst.ElementFactory.make(f'rtp{codec}depay')
        depay_options = ''
        for name, value in (('wait-for-keyframe', str(args.recovery == 'keyframe').lower()), ('request-keyframe', 'true')):
            if depay is not None and depay.find_property(name):
                depay_options += f' {name}={value}'
        if args.test:
            source = "videotestsrc is-live=true pattern=smpte ! video/x-raw,width=1280,height=720,framerate=30/1"
        else:
            source = (f'udpsrc address=127.0.0.1 port={args.port} buffer-size=1048576 '
                      f'caps="application/x-rtp,media=video,encoding-name={codec.upper()},clock-rate=90000" '
                      # Never discard arbitrary fragments of an otherwise
                      # intact H.265 picture solely to meet the UI budget.
                      f'! rtpjitterbuffer name=jitter latency={args.latency} drop-on-latency=false do-lost=true post-drop-messages=true '
                      f'! rtp{codec}depay{depay_options} '
                      f'! video/x-{codec},alignment=au ! {codec}parse ! {decode_element}')
        if args.window_handle and decoder == 'mppvideodec':
            from master.overlay_worker import run
            return run(Gst, GstVideo, source, args.window_handle, (args.window_width,args.window_height), event,
                       lambda: running and os.getppid() == parent_pid)
        # Raw frames can be replaced safely. Decouple conversion/display from
        # the compressed stream so a repaint cannot stall RTP depayloading.
        convert_chain = 'video/x-raw,format=NV12' if decoder == 'mppvideodec' else 'videoconvert n-threads=4 ! video/x-raw,format=RGBA'
        pipeline = Gst.parse_launch(source + " ! identity name=decoded_frames silent=true "
                                   "! queue name=latest_raw max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream "
                                   f"! videorate name=display_rate drop-only=true max-rate=60 ! {convert_chain} "
                                   "! appsink name=frames sync=false max-buffers=1 drop=true")
        sink = pipeline.get_by_name("frames")
        rate = pipeline.get_by_name("display_rate")
        decoded = pipeline.get_by_name("decoded_frames")
        jitter = pipeline.get_by_name("jitter")
        bus = pipeline.get_bus()
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer не смог запустить декодер")
        event(state="ready", decoder=decoder, version=Gst.version_string(), synthetic=args.test)
        last_stats, frames = time.monotonic(), 0
        previous_decoded = 0
        reported_caps = False
        pending_frame = False
        latest_sample = None
        pending_since = ack_wait_ms = 0.0
        jitter_drops = {}
        skipped = 0
        pipe_ms = pipeline_ms = 0.0
        extract_ms = convert_ms = share_ms = 0.0
        output = frame_output
        while running and os.getppid() == parent_pid:
            message = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS | Gst.MessageType.ELEMENT)
            if message:
                if message.type == Gst.MessageType.ERROR:
                    error, _ = message.parse_error()
                    raise RuntimeError(error.message)
                if message.type == Gst.MessageType.EOS:
                    break
                detail = message.get_structure()
                if detail is not None and detail.get_name() == "drop-msg":
                    reason = detail.get_value("reason")
                    jitter_drops[reason] = jitter_drops.get(reason, 0) + 1
            # Poll the ACK even between source frames. Keep just the newest
            # decoded sample while Qt owns the shared slot; discarding every
            # arrival during that interval lost the end of each RTP burst.
            if memory is not None and pending_frame:
                try:
                    pending_frame = not bool(os.read(sys.stdin.fileno(), 4096))
                    if not pending_frame:
                        ack_wait_ms = max(ack_wait_ms, (time.monotonic() - pending_since) * 1000)
                except BlockingIOError:
                    pass
            timeout = 8 * Gst.MSECOND if pending_frame else 0 if latest_sample is not None else 100 * Gst.MSECOND
            incoming = sink.emit("try-pull-sample", timeout)
            if incoming is not None:
                if latest_sample is not None:
                    skipped += 1
                latest_sample = incoming
            sample = None
            if not pending_frame and latest_sample is not None:
                sample, latest_sample = latest_sample, None
            if sample is not None:
                buf = sample.get_buffer()
                if buf.pts != Gst.CLOCK_TIME_NONE and pipeline.get_clock():
                    age = (pipeline.get_clock().get_time() - pipeline.get_base_time() - buf.pts) / Gst.MSECOND
                    if 0 <= age < 60000:
                        pipeline_ms = max(pipeline_ms, age)
                    # Catch up by dropping decoded pictures, never fragments
                    # needed to decode the following reference pictures.
                    if age > max(150, args.latency + 100):
                        skipped += 1
                        sample = None
            if sample is not None:
                # Discard excess source frames before the expensive RGBA
                # conversion. The sink keeps only the latest frame.
                info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
                width, height, stride = info.width, info.height, info.stride[0]
                if not (0 < width <= 4096 and 0 < height <= 2160):
                    raise RuntimeError("Неподдерживаемый размер кадра")
                buf = sample.get_buffer()
                sent_at = time.monotonic_ns()
                meta = GstVideo.buffer_get_video_meta(buf)
                if decoder == 'mppvideodec':
                    from master.nv12 import NV12Converter
                    if converter is None or (converter.width, converter.height) != (width,height):
                        if converter: converter.close()
                        converter = NV12Converter(width,height)
                    strides = list(meta.stride if meta is not None else info.stride)
                    offsets = list(meta.offset if meta is not None else info.offset)
                    measure = time.monotonic()
                    raw_nv12 = buf.extract_dup(0, buf.get_size())
                    extract_ms = max(extract_ms, (time.monotonic()-measure)*1000)
                    stride = width*4
                    raw = bytearray(stride*height)
                    measure = time.monotonic()
                    converter.convert(raw_nv12, strides, offsets, raw)
                    convert_ms = max(convert_ms, (time.monotonic()-measure)*1000)
                else:
                    offset = int(meta.offset[0]) if meta is not None else int(info.offset[0])
                    stride = int(meta.stride[0]) if meta is not None else stride
                    length = stride * height
                    if stride < width * 4 or offset + length > buf.get_size():
                        raise RuntimeError('Неверная разметка аппаратного видеокадра')
                    raw = buf.extract_dup(offset, length)
                header = struct.pack(">IIIIQ", width, height, stride, len(raw), sent_at) if args.frame_timestamps or memory is not None else struct.pack(">IIII", width, height, stride, len(raw))
                if memory is not None:
                    if len(raw) > memory.size:
                        raise RuntimeError("Кадр превышает размер видеобуфера")
                    measure = time.monotonic()
                    memory.buf[:len(raw)] = raw
                    share_ms = max(share_ms, (time.monotonic()-measure)*1000)
                    pending_frame = True
                    pending_since = time.monotonic()
                output.write(header)
                if memory is None:
                    output.write(raw)
                output.flush()
                pipe_ms = max(pipe_ms, (time.monotonic_ns() - sent_at) / 1e6)
                frames += 1
            now = time.monotonic()
            if now - last_stats >= 1:
                stats = jitter.get_property("stats") if jitter is not None else None
                transport = {name: stats.get_value(name) for name in ("num-pushed", "num-lost", "num-late", "num-duplicates", "avg-jitter") if stats.has_field(name)} if stats else {}
                frame_counts = {name: rate.get_property(name) for name in ("in", "out", "drop", "duplicate")}
                decoded_total = decoded.get_property("stats").get_value("num-buffers")
                if decoded_total and not reported_caps:
                    reported_caps = True
                    event(state='format', decoder_caps=decoded.get_static_pad('src').get_current_caps().to_string())
                event(state="video" if frames else "waiting", fps=round(frames / (now - last_stats), 1),
                      decoded_fps=round((decoded_total - previous_decoded) / (now - last_stats), 1),
                      decoded_frames=decoded_total,
                      frame_counts=frame_counts,
                      jitter_drop_events=jitter_drops,
                      **({"width": width, "height": height} if frames else {}),
                      jitterbuffer=transport, configured_buffer_ms=args.latency, recovery_mode=args.recovery,
                      pipeline_age_max_ms=round(pipeline_ms, 2), pipe_write_max_ms=round(pipe_ms, 2),
                      surface_copy_ms=round(extract_ms,2), color_convert_ms=round(convert_ms,2), shared_copy_ms=round(share_ms,2))
                if memory is not None:
                    event(state="display", frame_transport="shared_memory", display_skipped=skipped,
                          frame_ack_max_ms=round(ack_wait_ms, 2))
                previous_decoded = decoded_total
                frames, last_stats = 0, now
                skipped = 0
                ack_wait_ms = 0.0
                pipe_ms = pipeline_ms = 0.0
                extract_ms = convert_ms = share_ms = 0.0
        return 0
    except BrokenPipeError:
        return 0
    except Exception as exc:
        event(state="error", error=str(exc))
        return 1
    finally:
        activity.close()
        frame_output.close()
        if converter is not None: converter.close()
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
        if memory is not None:
            memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
