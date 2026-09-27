"""Bounded LAN microphone playback; credentials arrive through a private pipe."""
import json
import os
import signal
import sys
import time


def main():
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    Gst.init(None)
    request = json.loads(sys.stdin.buffer.read(16384))
    duration = min(60, max(5, int(request.get('seconds', 25))))
    pipeline = Gst.Pipeline.new('microphone-check')
    source = Gst.ElementFactory.make('rtspsrc', 'camera')
    source.set_property('location', 'rtsp://' + request['host'] + ':554/stream=0')
    source.set_property('user-id', request['username'])
    source.set_property('user-pw', request['password'])
    request.clear()
    source.set_property('protocols', 4)  # TCP avoids opening extra UDP ports.
    source.set_property('latency', 80)
    source.set_property('drop-on-latency', True)
    source.set_property('tcp-timeout', 5000000)
    pipeline.add(source)
    result = dict(state='no_audio', transport='lan_rtsp', recording=False,
                  audio_track=False, decoded_buffers=0, peak_db=None)
    running = True
    parent = os.getppid()

    def stop(*_):
        nonlocal running
        running = False

    def choose(_source, _number, caps):
        audio = caps.get_structure(0).get_string('media') == 'audio'
        result['audio_track'] |= audio
        return audio

    def added(_source, pad):
        caps = pad.get_current_caps() or pad.query_caps(None)
        spec = caps.get_structure(0)
        if spec.get_string('media') != 'audio' or result.get('codec'):
            return
        codec = spec.get_string('encoding-name')
        result['payload_type'] = spec.get_value('payload')
        decoders = {'OPUS': ('rtpopusdepay', 'opusdec'),
                    'MPEG4-GENERIC': ('rtpmp4gdepay', 'avdec_aac'),
                    'PCMA': ('rtppcmadepay', 'alawdec'), 'PCMU': ('rtppcmudepay', 'mulawdec')}
        if codec not in decoders:
            result.update(state='unsupported_codec', codec=codec)
            return
        depay, decoder = decoders[codec]
        try:
            branch = Gst.parse_bin_from_description(
                f'{depay} ! {decoder} ! audioconvert ! audioresample ! '
                'identity name=decoded silent=true ! level name=meter interval=250000000 ! '
                'volume volume=0.35 ! osxaudiosink sync=true', True)
            pipeline.add(branch)
            if pad.link(branch.get_static_pad('sink')) != Gst.PadLinkReturn.OK:
                raise ValueError('pad_link')
            branch.sync_state_with_parent()
            result['codec'] = codec
        except Exception as exc:
            result.update(state='decoder_error', error_type=type(exc).__name__)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    source.connect('select-stream', choose)
    source.connect('pad-added', added)
    started = time.monotonic()
    try:
        pipeline.set_state(Gst.State.PLAYING)
        bus = pipeline.get_bus()
        while running and os.getppid() == parent and time.monotonic() - started < duration:
            message = bus.timed_pop_filtered(250 * Gst.MSECOND,
                Gst.MessageType.ERROR | Gst.MessageType.EOS | Gst.MessageType.ELEMENT)
            if message:
                if message.type == Gst.MessageType.ERROR:
                    error, _ = message.parse_error()
                    # Never log RTSP URLs, SDP or authentication/debug text.
                    result.update(state='stream_error', error_domain=error.domain, error_code=error.code)
                    break
                if message.type == Gst.MessageType.EOS:
                    break
                structure = message.get_structure()
                if structure is not None and structure.get_name() == 'level':
                    peak = max(structure.get_value('peak'))
                    result['peak_db'] = round(max(result.get('peak_db') or -700, peak), 1)
            decoded = pipeline.get_by_name('decoded')
            if decoded:
                result['decoded_buffers'] = int(decoded.get_property('stats').get_value('num-buffers'))
            if not result['decoded_buffers'] and time.monotonic() - started > 10:
                break
        if result['decoded_buffers'] and result['state'] == 'no_audio':
            result['state'] = 'played'
    finally:
        pipeline.set_state(Gst.State.NULL)
        result['seconds'] = round(time.monotonic() - started, 1)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
