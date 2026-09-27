"""RTP forwarding and counters outside the GUI event loop."""
import socket
import threading
import time
from shared.rtp import parse, SequenceTracker


class RtpRelay:
    def __init__(self):
        self.socket = None
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.routes = (0, 0, 0, 0, None, 0)
        self.error = ''
        self._reset()

    def _reset(self):
        self.tracker = SequenceTracker()
        self.frames = set()
        self.bytes = self.packets = self.audio_packets = 0
        self.last_packet = 0.0
        self.last_audio_packet = 0.0
        self.peer = None
        self.forward_error = None

    def bind(self, address, port):
        self.close()
        self._reset()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        sock.settimeout(.02)
        try:
            sock.bind((address, port))
        except OSError as exc:
            self.error = str(exc)
            sock.close()
            return False
        self.socket = sock
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name='fitlab-rtp', daemon=True)
        self.thread.start()
        return True

    def configure(self, video=0, audio=0, record=0, stream=0, forward=None, record_audio=0):
        self.routes = (video, audio, record, stream, forward, record_audio)

    def _run(self):
        sock = self.socket
        while not self.stop_event.is_set():
            try:
                data, address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self._route(sock, data, address[0])

    def _route(self, sock, data, peer):
        try:
            header = parse(data)
        except ValueError:
            with self.lock:
                self.tracker.invalid += 1
            return
        now = time.monotonic()
        video, audio, record, stream, forward, record_audio = self.routes
        with self.lock:
            if self.peer and peer != self.peer and now - self.last_packet < 3:
                return
            if header.payload_type == 98:
                self.audio_packets += 1
                self.last_audio_packet = now
                ports = (audio, record_audio)
                forward = None
            else:
                self.peer, self.last_packet = peer, now
                self.tracker.observe(header, peer)
                if len(self.frames) < 600:
                    self.frames.add((header.ssrc, header.timestamp))
                self.bytes += len(data)
                self.packets += 1
                ports = (video, record, stream)
        for port in ports:
            if port:
                try:
                    sock.sendto(data, ('127.0.0.1', port))
                except OSError:
                    pass
        if forward:
            try:
                if forward[0] == peer:
                    raise ValueError('Адрес трансляции совпал с источником')
                sock.sendto(data, forward)
            except (OSError, ValueError):
                with self.lock:
                    self.forward_error = 'Не удалось передать поток по LAN'

    def snapshot(self):
        with self.lock:
            result = dict(bytes=self.bytes, packets=self.packets, audio_packets=self.audio_packets,
                          last_packet=self.last_packet, last_audio_packet=self.last_audio_packet, peer=self.peer, frames=self.frames,
                          integrity=self.tracker.snapshot(), restarts=self.tracker.restarts,
                          forward_error=self.forward_error)
            self.frames = set()
            self.forward_error = None
            return result

    def errorString(self):
        return self.error

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(.5)
            if self.thread.is_alive():
                raise RuntimeError('RTP relay did not stop')
            self.thread = None
        if self.socket is not None:
            self.socket.close()
            self.socket = None
