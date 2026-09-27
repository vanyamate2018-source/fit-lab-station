"""RX diversity bench: independent USB sessions, common authenticated WFB decoder.

Optional impairment drops forwarder datagrams in memory, never generates RF.
No video or encrypted packet contents are written to reports.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import plistlib
import random
import selectors
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from receiver import local_radio as base
from shared.radio_telemetry import RadioTelemetry

KNOWN_MACS = {"00:13:ef:f2:13:c1", "88:e6:28:6b:ca:ff"}


def inventory(allow_empty=False):
    from shared.usb_inventory import fast_devices
    devices = fast_devices()
    if devices is None:
        devices = legacy_inventory()
    devices.sort(key=lambda d: d["location"])
    if not (0 if allow_empty else 1) <= len(devices) <= 2 or any(not d["address"] for d in devices):
        raise ValueError("Нужны один или два RTL8812AU с разными USB-адресами")
    if len({d["address"] for d in devices}) != len(devices):
        raise ValueError("USB-адрес неоднозначен между шинами")
    return devices


def legacy_inventory():
    raw = subprocess.check_output(["/usr/sbin/ioreg", "-p", "IOUSB", "-a", "-l"], timeout=10)
    devices = []

    def walk(item):
        if isinstance(item, dict):
            if (item.get("idVendor"), item.get("idProduct")) == (0x0bda, 0x8812) and "bNumConfigurations" in item:
                devices.append({"address": item.get("USB Address", item.get("kUSBAddress")),
                                "location": item.get("locationID")})
            for value in item.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)
    walk(plistlib.loads(raw))
    devices.sort(key=lambda d: d["location"])
    return devices


def loss_phase(elapsed, enabled):
    if not enabled:
        return "normal", (0.0, 0.0)
    if elapsed < 15:
        return "baseline", (0.0, 0.0)
    if elapsed < 30:
        return "rx1_software_blackout", (1.0, 0.0)
    if elapsed < 45:
        return "rx2_software_blackout", (0.0, 1.0)
    return "independent_15_percent_loss", (.15, .15)


def main():
    os.umask(0o077)
    root = base.ROOT
    if not root.is_mount():
        raise ValueError("SSD FIT-LAB недоступен")
    duration = int(os.environ.get("FIT_LAB_VIEW_SECONDS", "0"))
    from shared.radio_settings import receiver_settings
    tuning = receiver_settings(int(os.environ.get("FIT_LAB_RADIO_CHANNEL", "161")), int(os.environ.get("FIT_LAB_RADIO_WIDTH", "20")))
    if not 0 <= duration <= 3600:
        raise ValueError("Недопустимая длительность")
    video_port = int(os.environ.get("FIT_LAB_RTP_PORT", "15600"))
    impairment = os.environ.get("FIT_LAB_TEST_LOSS") == "1"
    crypto_check = os.environ.get("FIT_LAB_VERIFY_CRYPTO") == "1"
    if duration == 0 and not impairment and not crypto_check:
        from receiver.resilient_radio import run
        run()
        return
    wrong_key_path = None
    wrong_codec = None
    devices = inventory()
    if impairment and len(devices) != 2:
        raise ValueError("Тест потерь рассчитан на два приёмника")
    lock = (root / "data/logs/.fit-lab-radio-prepare.lock").open("a")
    base.FILES.append(lock)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    logs = Path(tempfile.mkdtemp(prefix="dual-rx-", dir=root / "data/logs"))
    base.LOGS = logs
    summary = {"schema": 1, "operation": "dual_rx_only", "impairment": impairment,
               "duration_seconds": duration, "receivers": [], "phases": {}, "rtp_packets": 0,
               "rtp_bytes": 0, "rtsp_used": False, "tx_requested": False, "result": "starting"}

    def save():
        temp = logs / "summary.tmp"
        temp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        temp.replace(logs / "summary.json")

    def udp():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
        sock.bind(("127.0.0.1", 0))
        sock.setblocking(False)
        base.SOCKETS.append(sock)
        return sock

    try:
        save()
        base.event(state="starting", log_directory=str(logs), receivers=devices)
        key = base.get_key()
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
        for index, device in enumerate(devices):
            report = logs / f"rx{index + 1}-efuse.json"
            logical = logs / f"rx{index + 1}-logical.bin"
            process = base.spawn([base.DIAG, "--json", "--report", report, "macos-efuse-dump",
                                  "--vid", "0x0bda", "--pid", "0x8812", "--address", device["address"],
                                  "--logical-map-out", logical, "--i-understand-this-writes-control-registers"],
                                 f"rx{index + 1}-efuse.log")
            if process.wait(timeout=60) or json.loads(report.read_text()).get("result") != "pass":
                raise ValueError(f"RX{index + 1}: не удалось прочитать аппаратный профиль")
            mac, profile = base.derive_profile(logical.read_bytes(), expected_mac=None)
            if mac not in KNOWN_MACS:
                raise ValueError(f"Новый адаптер {mac}: аппаратный профиль ещё не проверен")
            summary["receivers"].append(dict(device, index=index, mac=mac, profile=profile, forwarded=0, dropped=0))
            save()
        if len({d["mac"] for d in summary["receivers"]}) != len(devices):
            raise ValueError("Прочитана повторная EFUSE: независимый выбор приёмников не подтверждён")
        if inventory() != devices:
            raise ValueError("USB-подключение изменилось во время подготовки")
        output = udp()
        forwards = [udp() for _ in devices]
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        base.SOCKETS.append(sender)
        aggregator_port = base.free_aggregator_port()
        codec = base.spawn([base.CODEC, "-a", aggregator_port, "-K", key, "-c", "127.0.0.1",
                            "-u", output.getsockname()[1], "-i", base.LINK_ID, "-p", "0"], "wfb-rx.log")
        time.sleep(.4)
        if codec.poll() is not None:
            raise ValueError("Не запустился WFB-декодер")
        wrong_port = None
        wrong_output = None
        if crypto_check:
            # Only the disposable negative-test key is created here. The paired
            # camera key is never read into Python or changed by this test.
            fd, key_name = tempfile.mkstemp(prefix="negative-key-", dir=root / "data/temp")
            wrong_key_path = Path(key_name)
            with os.fdopen(fd, "wb") as stream:
                stream.write(os.urandom(64))
            wrong_port = base.free_aggregator_port()
            wrong_output = udp()
            wrong_codec = base.spawn([base.CODEC, "-a", wrong_port, "-K", wrong_key_path,
                                      "-c", "127.0.0.1", "-u", wrong_output.getsockname()[1],
                                      "-i", base.LINK_ID, "-p", "0"], "wrong-key-wfb-rx.log")
            time.sleep(.2)
            if wrong_codec.poll() is not None:
                raise ValueError("Не запустился отрицательный тест ключа")
            summary["crypto_check"] = {"wrong_key_output": 0, "copied_frames": 0}
        radios = []
        for item, forward in zip(summary["receivers"], forwards):
            index = item["index"]
            command = [base.DIAG, "--json", "--report", logs / f"rx{index + 1}-radio.json", "rx-scan",
                       "--macos-usbhost", "--vid", "0x0bda", "--pid", "0x8812", "--address", item["address"],
                       "--init-before-rx", "--monitor-opmode-before-rx", "--rx-led", "--firmware", base.FW,
                       "--channel", tuning["channel"], "--bandwidth", tuning["width"], "--duration-ms", duration * 1000,
                       "--timeout-ms", "100", "--init-timeout-ms", "500", "--mac-source", tables["mac"],
                       "--bb-source", tables["bb"], "--rf-source", tables["rf"], "--cut-version", "0",
                       "--package-type", "0", "--support-interface", "2", "--support-platform", "0",
                       "--wfb-link-id", base.LINK_ID, "--wfb-radio-port", "0", "--rx-wlan-idx", index,
                       "--rx-aggregator", f"127.0.0.1:{forward.getsockname()[1]}", "--rx-mcs-index", "1",
                       "--i-understand-this-writes-registers"]
            for flag, value in item["profile"].items():
                command.extend(["--" + flag, value])
            item["command"] = [str(value) for value in command]
            radios.append(base.spawn(command, f"rx{index + 1}-radio.log"))
        rng = random.Random(25092026)
        mux = selectors.DefaultSelector()
        for index, sock in enumerate(forwards):
            mux.register(sock, selectors.EVENT_READ, index)
        mux.register(output, selectors.EVENT_READ, "rtp")
        if wrong_output is not None:
            mux.register(wrong_output, selectors.EVENT_READ, "wrong_key")
        telemetry = RadioTelemetry(logs / "wfb-rx.log")
        started = last_event = time.monotonic()
        active_start = None
        seen = set()
        last_rtp = 0.0
        previous_phase = None
        while duration == 0 or time.monotonic() - started < duration + 120:
            now = time.monotonic()
            if codec.poll() is not None:
                raise ValueError("WFB-декодер завершился")
            if wrong_codec is not None and wrong_codec.poll() is not None:
                raise ValueError("Отрицательный тест ключа прерван")
            for index, proc in enumerate(radios):
                item = summary["receivers"][index]
                if proc.poll() not in (None, 0) and not item.get("failed"):
                    item.update(failed=True, last_frame_monotonic=0,
                                error=f"RX{index + 1}: ошибка USB")
                    base.event(state="receiver_failed", receiver=index, warning=item["error"],
                               log_directory=str(logs))
            if all(p.poll() is not None for p in radios):
                if all(item.get("failed") for item in summary["receivers"]):
                    raise ValueError("Оба приёмника недоступны" if len(radios) == 2 else "Приёмник недоступен")
                break
            elapsed = now - active_start if active_start else 0
            phase, loss = loss_phase(elapsed, impairment)
            if phase != previous_phase:
                base.event(state="test_phase", phase_name=phase, log_directory=str(logs))
                previous_phase = phase
            totals = summary["phases"].setdefault(phase, {"input": [0, 0], "dropped": [0, 0], "rtp": 0,
                                                        "first_elapsed": round(elapsed, 2), "last_elapsed": 0})
            totals["last_elapsed"] = round(elapsed, 2)
            for selected, _ in mux.select(.05):
                for _ in range(256):
                    try:
                        data, _ = selected.fileobj.recvfrom(65535)
                    except BlockingIOError:
                        break
                    if selected.data == "wrong_key":
                        summary["crypto_check"]["wrong_key_output"] += 1
                    elif selected.data == "rtp":
                        if len(data) >= 14 and data[0] >> 6 == 2 and not 192 <= data[1] <= 223:
                            sender.sendto(data, ("127.0.0.1", video_port))
                            summary["rtp_packets"] += 1
                            summary["rtp_bytes"] += len(data)
                            totals["rtp"] += 1
                            last_rtp = now
                    else:
                        index = selected.data
                        item = summary["receivers"][index]
                        item["input_frames"] = item.get("input_frames", 0) + 1
                        item["last_frame_monotonic"] = now
                        if len(data) >= 17:
                            item["rssi_dbm"] = int.from_bytes(data[5:6], signed=True)
                            noise = int.from_bytes(data[9:10], signed=True)
                            item["snr_db"] = item["rssi_dbm"] - noise if noise != 127 else None
                        seen.add(index)
                        if len(seen) == len(devices) and active_start is None:
                            active_start = now
                        totals["input"][index] += 1
                        if rng.random() < loss[index]:
                            totals["dropped"][index] += 1
                            summary["receivers"][index]["dropped"] += 1
                        else:
                            sender.sendto(data, ("127.0.0.1", aggregator_port))
                            summary["receivers"][index]["forwarded"] += 1
                            if wrong_port is not None:
                                sender.sendto(data, ("127.0.0.1", wrong_port))
                                summary["crypto_check"]["copied_frames"] += 1
            if now - last_event >= 1:
                summary["result"] = "receiving" if now - last_rtp < 2 else "waiting"
                base.event(state=summary["result"], rtp_packets=summary["rtp_packets"],
                           rtp_bytes=summary["rtp_bytes"], radio=telemetry.read(),
                           test_phase=phase if impairment else None,
                           receivers=[{k: v for k, v in item.items() if k != "command"} for item in summary["receivers"]],
                           log_directory=str(logs))
                save()
                last_event = now
        mux.close()
        if any(p.poll() is None for p in radios):
            raise ValueError("Истёк срок ожидания приёмников")
        summary["result"] = "rtp_received" if summary["rtp_packets"] else "no_rtp"
    except KeyboardInterrupt:
        summary["result"] = "stopped_by_user"
    except Exception as exc:
        summary.update(result="error", error=str(exc))
        base.event(state="error", error=str(exc), log_directory=str(logs))
        raise
    finally:
        base.cleanup()
        if wrong_key_path is not None:
            wrong_key_path.unlink(missing_ok=True)
        for item in summary["receivers"]:
            report = logs / f"rx{item['index'] + 1}-radio.json"
            if report.exists():
                raw = json.loads(report.read_text())
                item["result"] = raw.get("result")
                item["counters"] = raw.get("counters")
                item["rx"] = raw.get("rx_fixture")
                item["error"] = raw.get("error")
        summary["codec_totals"] = base.summarize_codec(logs / "wfb-rx.log")
        if "crypto_check" in summary:
            check = summary["crypto_check"]
            check["wrong_key_totals"] = base.summarize_codec(logs / "wrong-key-wfb-rx.log")
            check["passed"] = bool(summary["rtp_packets"] > 0 and check["wrong_key_output"] == 0
                                   and check["wrong_key_totals"]["decrypt_errors"] > 0
                                   and check["wrong_key_totals"]["outgoing_packets"] == 0)
        save()
        base.event(state="finished", result=summary["result"], log_directory=str(logs), rtp_packets=summary["rtp_packets"])
        print(f"Отчёт: {logs / 'summary.json'}", flush=True)


def stop_once(*_):
    # A second Stop/Quit must not interrupt finally while USB-owning children
    # are being terminated. Otherwise they outlive the station and seize RX.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_once)
    signal.signal(signal.SIGINT, stop_once)
    main()
