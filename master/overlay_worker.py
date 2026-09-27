"""Direct native video presentation into an existing receiver window."""
import json
import os
import sys
import time


def run(Gst, GstVideo, source, window, size, event, alive):
    pipeline = Gst.parse_launch(source + ' ! identity name=decoded_frames silent=true ! queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream ! xvimagesink name=screen sync=false force-aspect-ratio=true')
    screen = pipeline.get_by_name('screen')
    GstVideo.VideoOverlay.set_window_handle(screen, window)
    GstVideo.VideoOverlay.set_render_rectangle(screen, 0, 0, *size)
    GstVideo.VideoOverlay.handle_events(screen, False)
    bus = pipeline.get_bus()
    decoded = pipeline.get_by_name('decoded_frames')
    renderer = screen
    jitter = pipeline.get_by_name('jitter')
    command_buffer = b''
    previous = previous_decoded = 0
    heartbeat_count = 0
    heartbeat_time = 0.0
    stamp = time.monotonic()
    first_decoded_at = None
    os.set_blocking(sys.stdin.fileno(), False)
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('Не удалось включить аппаратный вывод видео')
        event(state='ready', decoder='mppvideodec', version=Gst.version_string(), frame_transport='native_overlay', renderer='xvideo')
        while alive():
            message = bus.timed_pop_filtered(20 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if message:
                if message.type == Gst.MessageType.ERROR:
                    error, detail = message.parse_error()
                    raise RuntimeError(error.message)
                break
            try:
                command_buffer += os.read(sys.stdin.fileno(), 4096)
                while b'\n' in command_buffer:
                    line, command_buffer = command_buffer.split(b'\n', 1)
                    command = json.loads(line)
                    if isinstance(command.get('window'), int) and command['window'] > 0:
                        GstVideo.VideoOverlay.set_window_handle(screen, command['window'])
                        if 0 < command.get('width', 0) <= 16384 and 0 < command.get('height', 0) <= 16384:
                            GstVideo.VideoOverlay.set_render_rectangle(screen, 0, 0, command['width'], command['height'])
                        GstVideo.VideoOverlay.expose(screen)
            except BlockingIOError:
                pass
            now = time.monotonic()
            if now - heartbeat_time >= .2:
                heartbeat_rendered = renderer.get_property('stats').get_value('rendered')
                if heartbeat_rendered > heartbeat_count:
                    event(state='presented', frame_transport='native_overlay')
                heartbeat_count, heartbeat_time = heartbeat_rendered, now
            if now - stamp >= 1:
                stats = renderer.get_property('stats')
                rendered = stats.get_value('rendered')
                count = decoded.get_property('stats').get_value('num-buffers')
                if count and first_decoded_at is None:
                    first_decoded_at = now
                # An absent camera is not a renderer failure. Start the watchdog
                # only after an actual decoded frame reaches the output.
                if not rendered and first_decoded_at is not None and now - first_decoded_at > 6:
                    raise RuntimeError('Аппаратный вывод не показал кадры')
                caps = decoded.get_static_pad('src').get_current_caps()
                dimensions = {}
                if caps:
                    structure = caps.get_structure(0)
                    dimensions = dict(width=structure.get_value('width'), height=structure.get_value('height'))
                transport = jitter.get_property('stats') if jitter else None
                event(state='video' if rendered > previous else 'waiting', frame_transport='native_overlay', renderer='xvideo',
                      fps=round((rendered-previous)/(now-stamp),1), presented_fps=round((rendered-previous)/(now-stamp),1),
                      decoded_fps=round((count-previous_decoded)/(now-stamp),1), rendered_frames=rendered,
                      render_dropped=stats.get_value('dropped'), **dimensions,
                      jitterbuffer={name: transport.get_value(name) for name in ('num-pushed','num-lost','num-late')} if transport else {})
                previous, previous_decoded, stamp = rendered, count, now
    finally:
        pipeline.set_state(Gst.State.NULL)
    return 0
