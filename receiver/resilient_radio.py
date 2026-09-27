"""Continuous dual RX with per-device reinitialization and a shared WFB decoder."""
import fcntl
import hashlib
import json
import os
import selectors
import signal
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from receiver import local_radio as base
from receiver.dual_radio import inventory
from receiver.recovery import RadioRecovery
from shared.radio_telemetry import RadioTelemetry


class Backend:
    def __init__(self, logs, tables, ports, control=None):
        self.logs, self.tables, self.ports = logs, tables, ports
        self.control = control
        self.discovery_channels = []
        self.last_reports = {}
        from shared.radio_settings import receiver_settings
        self.tuning = receiver_settings(int(os.environ.get("FIT_LAB_RADIO_CHANNEL", "161")), int(os.environ.get("FIT_LAB_RADIO_WIDTH", "20")))

    def folder(self, job):
        return self.logs / f"usb-{job.device['location']}-{job.device['address']}-{job.generation}-try-{job.attempt}"

    def spawn(self, command, path):
        # The child keeps its descriptor; the parent does not leak one per retry.
        with path.open("wb") as stream:
            return subprocess.Popen(list(map(str, command)), stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    env=dict(os.environ, FIT_LAB_LED_MODE='standby' if self.discovery_channels else 'receive'))

    def prepare(self, job):
        folder = self.folder(job)
        folder.mkdir()
        return self.spawn([base.DIAG, "--json", "--report", folder / "efuse.json", "macos-efuse-dump",
                           "--vid", "0x0bda", "--pid", "0x8812", "--address", job.device["address"],
                           "--logical-map-out", folder / "logical.bin",
                           "--i-understand-this-writes-control-registers"], folder / "efuse.log")

    def profile(self, job):
        folder = self.folder(job)
        if json.loads((folder / "efuse.json").read_text()).get("result") != "pass":
            raise ValueError("Не удалось проверить профиль USB-приёмника")
        return base.derive_profile((folder / "logical.bin").read_bytes(), expected_mac=None)

    def receive(self, job):
        job.tx_ready = False
        folder = self.folder(job)
        folder.mkdir(exist_ok=True)
        if job.tuning is None:
            job.tuning = dict(self.discovery_channels[job.index % len(self.discovery_channels)]
                              if self.discovery_channels else self.tuning)
        tuning = job.tuning
        t = self.tables
        args = [base.DIAG, "--json", "--report", folder / "radio.json", "rx-scan", "--macos-usbhost",
                "--vid", "0x0bda", "--pid", "0x8812", "--address", job.device["address"],
                "--init-before-rx", "--monitor-opmode-before-rx", "--rx-led", "--firmware", base.FW,
                "--channel", tuning["channel"], "--bandwidth", tuning["width"], "--duration-ms", "0", "--timeout-ms", "100",
                "--init-timeout-ms", "500", "--mac-source", t["mac"], "--bb-source", t["bb"],
                "--rf-source", t["rf"], "--cut-version", "0", "--package-type", "0",
                "--support-interface", "2", "--support-platform", "0", "--wfb-link-id", base.LINK_ID,
                "--wfb-radio-port", "0", "--rx-wlan-idx", job.index,
                "--rx-aggregator", f"127.0.0.1:{self.ports[job.index]}", "--rx-mcs-index", "1",
                "--i-understand-this-writes-registers"]
        for flag, value in job.profile.items():
            args.extend(["--" + flag, value])
        if self.control and (job.index == 0 or self.control.diversity_enabled):
            # Dedicated endpoint per process; the central router feeds only
            # one owner. The other bridge keeps receiving, including stream 32.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(('127.0.0.1', 0))
                job.tx_port = probe.getsockname()[1]
            args = [base.DIAG, '--json', '--report', folder/'radio.json', 'bridge-run', '--macos-usbhost',
                    '--vid', '0x0bda', '--pid', '0x8812', '--address', job.device['address'],
                    '--init-before-tx', '--firmware', base.FW, '--channel', tuning['channel'],
                    '--bandwidth', tuning['width'], '--bind', f'127.0.0.1:{job.tx_port}',
                    '--duration-ms', '0', '--max-datagrams', '0', '--rx-timeout-ms', '5',
                    '--ready-file', folder / 'bridge-ready.json',
                    '--tx-burst-limit', '2', '--tx-min-interval-us', '1000', '--rx-led',
                    '--mac-source', t['mac'], '--bb-source', t['bb'], '--rf-source', t['rf'],
                    '--cut-version', '0', '--package-type', '0', '--support-interface', '2', '--support-platform', '0',
                    '--wfb-link-id', base.LINK_ID, '--wfb-radio-port', '0', '--rx-wlan-idx', job.index,
                    '--rx-aggregator', f'127.0.0.1:{self.ports[job.index]}', '--rx-mcs-index', '1',
                    '--rx-forward', f'{base.LINK_ID}:32=127.0.0.1:{self.control.aggregator}',
                    '--tx-power-mode', 'manual-index', '--tx-power-index', '10',
                    '--i-understand-this-writes-registers']
            for flag, value in job.profile.items():
                args.extend(['--'+flag, value])
        return self.spawn(args, folder / "radio.log")

    def ready(self, job):
        return job.tx_port is not None and (self.folder(job) / 'bridge-ready.json').is_file()

    def finish(self, job):
        report = self.folder(job) / "radio.json"
        if job.index is not None and report.exists():
            self.last_reports[job.index] = str(report)


def run():
    from shared.media_activity import MediaActivity
    activity = MediaActivity(base.ROOT / "data")
    activity.start()
    logs = Path(tempfile.mkdtemp(prefix="continuous-rx-", dir=base.ROOT / "data/logs"))
    base.LOGS = logs
    lock = (base.ROOT / "data/logs/.fit-lab-radio-prepare.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sockets, processes = [], []
    summary = dict(schema=2, operation="continuous_dual_rx", duration_seconds=0,
                   tx_requested=False, rtp_packets=0, rtp_bytes=0, result="starting", receivers=[])
    pool = ThreadPoolExecutor(max_workers=1)
    recovery = None
    backend = None
    control = None
    parent_pid = os.getppid()

    def udp():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
        sock.bind(("127.0.0.1", 0))
        sock.setblocking(False)
        sockets.append(sock)
        return sock

    def save():
        temporary = logs / "summary.tmp"
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(logs / "summary.json")

    try:
        if base.run(["git", "-C", base.REPO, "rev-parse", "HEAD"]).strip() != base.REV:
            raise ValueError("Изменилась версия радио backend")
        if hashlib.sha256(base.FW.read_bytes()).hexdigest() != base.FW_SHA:
            raise ValueError("Не совпадает SHA-256 firmware")
        tables = {}
        for name, (filename, expected) in base.TABLE_BLOBS.items():
            path = base.TABLE_ROOT / filename
            data = path.read_bytes()
            if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != expected:
                raise ValueError(f"Изменена таблица {name}")
            tables[name] = path
        key = base.get_key()
        output, rx1, rx2 = udp(), udp(), udp()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sockets.append(sender)
        aggregator = base.free_aggregator_port()
        with (logs / "wfb-rx.log").open("wb") as stream:
            codec = subprocess.Popen(list(map(str, [base.CODEC, "-a", aggregator, "-K", key,
                "-c", "127.0.0.1", "-u", output.getsockname()[1], "-i", base.LINK_ID, "-p", "0"])),
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        processes.append(codec)
        from receiver.udp_ready import wait_for_udp_receiver
        wait_for_udp_receiver(codec, aggregator)
        summary['video_input_port'] = aggregator
        summary['tx_requested'] = os.environ.get('FIT_LAB_CONTROL') == '1'
        if summary['tx_requested']:
            from receiver.control_link import ControlLink
            try:
                control = ControlLink(logs, key)
                summary['control_input_port'] = control.aggregator
            except (OSError, ValueError) as exc:
                base.event(state='notice', notice='Обратный канал недоступен · видеоприём продолжается')
                summary['control_error'] = str(exc)
        backend = Backend(logs, tables, [rx1.getsockname()[1], rx2.getsockname()[1]], control)
        recovery = RadioRecovery(backend, lambda text: base.event(state="notice", notice=text))
        summary["receivers"] = recovery.receivers
        telemetry = RadioTelemetry(logs / "wfb-rx.log")
        from receiver.camera_identity import CameraIdentity
        from shared.pairing_store import PairingStore
        identities = CameraIdentity(PairingStore(base.ROOT / 'data'), base.LINK_ID)
        last_identity_event = {}
        pending = pool.submit(inventory, True)
        last_scan = last_event = last_rtp = 0.0
        last_connections = ()
        previous_frames = [0, 0]
        video_port = int(os.environ.get("FIT_LAB_RTP_PORT", "15600"))
        with selectors.DefaultSelector() as mux:
            for source, name in ((rx1, 0), (rx2, 1), (output, "rtp")):
                mux.register(source, selectors.EVENT_READ, name)
            if control:
                mux.register(control.encoded, selectors.EVENT_READ, 'tx')
            while True:
                now = time.monotonic()
                if os.getppid() != parent_pid:
                    raise KeyboardInterrupt
                if codec.poll() is not None:
                    raise ValueError("WFB-декодер завершился")
                devices = None
                if pending is not None and pending.done():
                    try:
                        devices = pending.result()
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass  # A failed enumeration is not proof of disconnection.
                    pending, last_scan = None, now
                if pending is None and now - last_scan >= .25:
                    pending = pool.submit(inventory, True)
                recovery.tick(now, devices)
                if control:
                    control.select_receiver(recovery, now)
                    summary['control'] = dict(control.poll(now))
                # Deliver decoded video first and bound each RX batch. A burst
                # from one USB port must not hold the other or RTP in a queue.
                ready = sorted(mux.select(.025), key=lambda event: event[0].data != "rtp")
                for selected, _ in ready:
                    for _ in range(32):
                        try:
                            data, _ = selected.fileobj.recvfrom(65535)
                        except BlockingIOError:
                            break
                        if selected.data == "rtp":
                            if len(data) >= 12 and data[0] >> 6 == 2:
                                types = summary.setdefault('rtp_payload_types', {})
                                pt = str(data[1] & 127)
                                types[pt] = types.get(pt, 0) + 1
                            if len(data) >= 14 and data[0] >> 6 == 2 and not 192 <= data[1] <= 223:
                                sender.sendto(data, ("127.0.0.1", video_port))
                                summary["rtp_packets"] += 1
                                summary["rtp_bytes"] += len(data)
                                last_rtp = now
                        elif selected.data == 'tx':
                            control.forward_encoded(data)
                        elif recovery.received(selected.data, now):
                            identity = identities.feed(data, now)
                            if identity and now - last_identity_event.get(identity, 0) >= .5:
                                base.event(state='camera_identified', camera_identity=identity,
                                           camera_identity_monotonic=now)
                                last_identity_event[identity] = now
                            item = recovery.receivers[selected.data]
                            if len(data) >= 17:
                                item["rssi_dbm"] = int.from_bytes(data[5:6], signed=True)
                                noise = int.from_bytes(data[9:10], signed=True)
                                item["snr_db"] = item["rssi_dbm"] - noise if noise != 127 else None
                            sender.sendto(data, ("127.0.0.1", aggregator))
                            item["forwarded"] += 1
                connections = tuple(item['connection'] for item in recovery.receivers)
                if now - last_event >= 1 or connections != last_connections:
                    active = []
                    for index, item in enumerate(recovery.receivers):
                        item["packets_per_second"] = round((item["input_frames"] - previous_frames[index]) / (now - last_event), 1) if last_event else 0
                        previous_frames[index] = item["input_frames"]
                        if item["last_frame_monotonic"] and now - item["last_frame_monotonic"] < 2:
                            active.append(index + 1)
                    summary["result"] = "receiving" if now - last_rtp < 2 else "waiting"
                    base.event(state=summary["result"], receivers=recovery.receivers,
                               rtp_payload_types=summary.get('rtp_payload_types', {}),
                               radio=telemetry.read(), log_directory=str(logs),
                               control=summary.get('control', {'state': 'disabled'}),
                               diversity={"mode": "packet_merge", "active_receivers": active,
                                          "state": "dual" if len(active) == 2 else "single" if active else "waiting"})
                    save()
                    last_event = now
                    last_connections = connections
    except KeyboardInterrupt:
        summary["result"] = "stopped_by_user"
    except Exception as exc:
        summary.update(result="error", error=str(exc))
        base.event(state="error", error=str(exc))
    finally:
        # Parent disappearance also reaches this path without a stop signal.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        activity.close()
        if recovery:
            recovery.close()
            processes.extend(j.process for j in recovery.jobs.values() if j.process is not None)
        if control:
            processes.extend(control.children)
        from receiver.process_cleanup import stop_children
        summary['shutdown_pending_pids'] = stop_children(processes)
        if control:
            control.close(stop_processes=False)
        if backend and recovery:
            for job in recovery.jobs.values():
                backend.finish(job)
            summary["last_radio_reports"] = backend.last_reports
        for sock in sockets:
            sock.close()
        pool.shutdown(wait=True, cancel_futures=True)
        lock.close()
        summary["codec_totals"] = base.summarize_codec(logs / "wfb-rx.log")
        save()
        base.event(state="finished", result=summary["result"], log_directory=str(logs))
