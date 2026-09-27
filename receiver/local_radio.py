"""Receive-only Mac bench backend. Owns USB/WFB children, never the UI.

Adapted from the verified FIT-LAB radio launcher; the key is passed only by path.
Pinned external binaries, firmware and tables remain on the FIT-LAB SSD.
"""
from __future__ import annotations

import base64
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

from shared.radio_telemetry import RadioTelemetry

ROOT = Path(os.environ.get('FIT_LAB_ROOT', Path(__file__).resolve().parents[2]))
REPO = ROOT / 'experiments/wfb-link'
DIAG = REPO / 'target/release/wfb-radio-diag'
CODEC = REPO / 'target/wfb-ng-macos/bin/wfb_rx'
FW = ROOT / 'experiments/rtl8812au-firmware-pYXTVZ/rtl8812aefw.bin'
REV = '6653690d53ac5c5c690e258453fac2b08636ad0c'
FW_SHA = 'abdcca4e8bf76ebfba23d433de310ffefebd0ff9d01990639d4cd9602b32b71a'
EXPECTED_MAC = '00:13:ef:f2:13:c1'
TABLE_ROOT = ROOT / 'experiments/rtl8812au-tables-7344855'
TABLE_BLOBS = {
    'mac': ('halhwimg8812a_mac.c', 'febfa8010f643dad696786db9dccc8baa1a73ff2'),
    'bb': ('halhwimg8812a_bb.c', '0d2cb51c04b3fb242fed4819d31448c75694a25c'),
    'rf': ('halhwimg8812a_rf.c', '02f64522d634f31acf5b1e3ae55c504811b29a11'),
}
CHANNEL, WIDTH, LINK_ID, RADIO_PORT = 161, 20, 7669206, 0
DURATION_MS = int(os.environ.get('FIT_LAB_VIEW_SECONDS', '60')) * 1000
if not 0 <= DURATION_MS <= 3600000:
    raise ValueError('FIT_LAB_VIEW_SECONDS должен быть от 1 до 3600.')
MAX_CAPTURE_BYTES = 128 * 1024 * 1024
PROCS = []
FILES = []
SOCKETS = []
LOGS = None
SUMMARY = {'version': '2.2.0-fitlab', 'operation': 'radio_video_rx_only',
           'channel': CHANNEL, 'bandwidth_mhz': WIDTH, 'link_id': LINK_ID,
           'radio_port': RADIO_PORT, 'tx_requested': False,
           'rtsp_used': False, 'camera_modified': False,
           'video_recorded': False, 'temporary_raw_radio_capture': False, 'decoder_external': True,
           'video_display_confirmed': False, 'result': 'starting',
           'recovered_datagrams': 0, 'rtp_packets': 0, 'rtp_bytes': 0,
           'relayed_packets': 0, 'non_rtp_datagrams': 0}


def event(**data):
    print('FITLAB_EVENT ' + json.dumps(data, ensure_ascii=False), flush=True)


def say(text):
    print(text, flush=True)


def save_summary():
    if LOGS is not None:
        temp = LOGS / 'summary.json.tmp'
        temp.write_text(json.dumps(SUMMARY, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(LOGS / 'summary.json')
        event(state=SUMMARY['result'], log_directory=str(LOGS))


def run(args, timeout=20):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True,
                          text=True, timeout=timeout).stdout


def spawn(args, name):
    log = (LOGS / name).open('wb')
    FILES.append(log)
    proc = subprocess.Popen([str(x) for x in args], stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    PROCS.append(proc)
    return proc


def cleanup():
    for proc in reversed(PROCS):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for proc in reversed(PROCS):
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)
    for item in SOCKETS + FILES:
        item.close()


def usb_devices():
    raw = subprocess.run(['/usr/sbin/ioreg', '-p', 'IOUSB', '-a', '-l'],
                         check=True, capture_output=True, timeout=20).stdout
    devices = []
    def walk(obj):
        if isinstance(obj, dict):
            if (obj.get('idVendor'), obj.get('idProduct')) == (0x0bda, 0x8812) and 'bNumConfigurations' in obj:
                devices.append({'location': obj.get('locationID'),
                                'serial': obj.get('USB Serial Number', obj.get('kUSBSerialNumberString'))})
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(plistlib.loads(raw))
    if len(devices) != 1:
        raise ValueError(f'Нужен ровно один RTL8812AU; обнаружено: {len(devices)}.')
    return devices[0]


def get_key():
    from shared.pairing_store import PairingStore
    PairingStore(ROOT / 'data').guard()
    p = ROOT / 'private/runcam/gs.key'
    if not p.is_file() or p.is_symlink() or p.stat().st_size != 64:
        raise ValueError('Нет корректного ключа в /Volumes/FIT-LAB/private/runcam/gs.key.')
    return p


def derive_profile(logical, expected_mac=EXPECTED_MAC):
    if len(logical) != 512 or logical[:2] != b'\x29\x81':
        raise ValueError('Не удалось подтвердить формат заводской карты текущего адаптера.')
    mac = ':'.join(f'{x:02x}' for x in logical[0xd7:0xdd])
    if expected_mac is not None and mac != expected_mac:
        raise ValueError(f'Подключён адаптер {mac}, ожидался {expected_mac}. Радио не запускается.')
    if (int.from_bytes(logical[0xd0:0xd2], 'little'),
        int.from_bytes(logical[0xd2:0xd4], 'little')) != (0x0bda, 0x8812):
        raise ValueError('USB-идентификаторы в EFUSE отличаются от ожидаемых.')
    pa, l2, l5 = [0 if logical[i] == 255 else logical[i] for i in (0xbc, 0xbd, 0xbf)]
    ep2, ep5, el2, el5 = pa & 0x30 == 0x30, pa & 3 == 3, l2 & 0x88 == 0x88, l5 & 0x88 == 0x88
    rfe_raw = logical[0xca]
    if rfe_raw == 255:
        rfe = 0  # upstream USB fallback, without a registry override
    elif rfe_raw & 128:
        rfe = (3 if el2 and ep2 else 0) if el5 and ep5 else (2 if el5 else 4)
    else:
        rfe = rfe_raw & 63
        if rfe == 4 and any((ep2, ep5, el2, el5)):
            rfe = 0
    if rfe not in (0, 1, 2, 3, 4):
        raise ValueError(f'Аппаратный профиль RFE {rfe} не включён в этот ограниченный запуск.')
    profile = {
        'board-type': (int(el2) << 4) | (int(ep2) << 3) | (int(el5) << 7) | (int(ep5) << 6),
        'type-glna': (((l2 >> 4) & 3) << 2 | (l2 & 3)) if el2 else 0,
        'type-gpa': (((l2 >> 6) & 1) << 2 | ((l2 >> 2) & 1)) if ep2 else 0,
        'type-alna': (((l5 >> 4) & 3) << 2 | (l5 & 3)) if el5 else 0,
        'type-apa': (((l5 >> 6) & 1) << 2 | ((l5 >> 2) & 1)) if ep5 else 0,
        'crystal-cap': (0x20 if logical[0xb9] == 255 else logical[0xb9]) & 63,
        'rfe-type': rfe,
    }
    return mac, profile


def parse_rtp(data):
    if len(data) < 14 or data[0] >> 6 != 2 or 192 <= data[1] <= 223:
        return None
    end = len(data)
    start = 12 + 4 * (data[0] & 15)
    if start > end:
        return None
    if data[0] & 16:
        if start + 4 > end:
            return None
        start += 4 + 4 * int.from_bytes(data[start + 2:start + 4], 'big')
    if data[0] & 32:
        pad = data[-1]
        if not pad or pad > end - start:
            return None
        end -= pad
    if start + 2 > end:
        return None
    body = data[start:end]
    if body[0] & 128 or not body[1] & 7:  # invalid HEVC payload header
        return None
    return data[1] & 127, struct.unpack('!I', data[8:12])[0], body


def get_parameter_sets(body, sets):
    kind = (body[0] >> 1) & 63
    nals = [body]
    if kind == 48:  # AP, no DONL (default non-interleaved HEVC mode)
        nals = []
        pos = 2
        while pos + 2 <= len(body):
            n = int.from_bytes(body[pos:pos + 2], 'big')
            pos += 2
            if n < 2 or pos + n > len(body):
                return
            nals.append(body[pos:pos + n])
            pos += n
        if pos != len(body):
            return
    for nal in nals:
        kind = (nal[0] >> 1) & 63
        if kind in (32, 33, 34) and len(nal) <= 8192:
            sets[kind] = base64.b64encode(nal).decode('ascii')


def make_sdp(port, pt, sets):
    lines = ['v=0', f'o=- {int(time.time())} 1 IN IP4 127.0.0.1',
             's=FIT-LAB RADIO - RunCam H265', 'c=IN IP4 127.0.0.1', 't=0 0',
             f'm=video {port} RTP/AVP {pt}', f'a=rtpmap:{pt} H265/90000', 'a=recvonly']
    fmtp = [f'{name}={sets[k]}' for k, name in ((32, 'sprop-vps'), (33, 'sprop-sps'), (34, 'sprop-pps')) if k in sets]
    if fmtp:
        lines.append(f'a=fmtp:{pt} ' + ';'.join(fmtp))
    return '\r\n'.join(lines) + '\r\n'


def free_aggregator_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(('0.0.0.0', 0))
        return s.getsockname()[1]


def main():
    global LOGS
    if sys.platform != 'darwin':
        raise ValueError('Нужна macOS.')
    os.umask(0o077)
    if not os.path.ismount(ROOT) or not (ROOT / 'data/logs').is_dir():
        raise ValueError('Накопитель FIT-LAB недоступен.')
    for p in (DIAG, CODEC):
        if not p.is_file() or not os.access(p, os.X_OK):
            raise ValueError(f'Не найдена программа: {p}')
    key = get_key()
    if run(['git', '-C', REPO, 'rev-parse', 'HEAD']).strip() != REV:
        raise ValueError('Версия wfb-link отличается от проверенной.')
    if hashlib.sha256(FW.read_bytes()).hexdigest() != FW_SHA:
        raise ValueError('Микропрограмма отличается от проверенной.')
    tables = {}
    for name, (filename, expected) in TABLE_BLOBS.items():
        p = TABLE_ROOT / filename
        data = p.read_bytes()
        if hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest() != expected:
            raise ValueError(f'Изменена таблица: {p}')
        tables[name] = p
    lock = (ROOT / 'data/logs/.fit-lab-radio-prepare.lock').open('a')
    FILES.append(lock)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('Другой сценарий FIT-LAB уже использует радио.') from None
    usb = usb_devices()
    LOGS = Path(tempfile.mkdtemp(prefix='runcam-radio-video-', dir=ROOT / 'data/logs'))
    SUMMARY['log_directory'] = str(LOGS)
    save_summary()
    say('FIT-LAB RADIO VIDEO 2.2 — канал 161 / 20 МГц; только приём.')
    say(f'Отчёты: {LOGS}')
    say('Читаю параметры НОВОГО свистка; старую карту EFUSE не использую…')
    ef_report, logical_file = LOGS / 'adapter-efuse.json', LOGS / 'adapter-logical.bin'
    ef = spawn([DIAG, '--json', '--report', ef_report, 'macos-efuse-dump',
                '--vid', '0x0bda', '--pid', '0x8812', '--raw-out', LOGS / 'adapter-raw.bin',
                '--logical-map-out', logical_file, '--i-understand-this-writes-control-registers'], 'adapter.log')
    ef_rc = ef.wait(timeout=60)
    er = json.loads(ef_report.read_text())
    if ef_rc or er.get('result') != 'pass':
        raise ValueError(f"Чтение параметров свистка не удалось: {er.get('error')}")
    mac, profile = derive_profile(logical_file.read_bytes())
    SUMMARY.update(adapter_mac=mac, profile_from_current_efuse=profile,
                   full_rf_calibration_confirmed=False)
    say(f"Адаптер {mac}; board={profile['board-type']:#x}, RFE={profile['rfe-type']}, кварц={profile['crystal-cap']:#x}.")
    if usb_devices() != usb:
        raise ValueError('USB-подключение изменилось. Запуск отменён.')

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    SOCKETS.append(receiver)
    receiver.bind(('127.0.0.1', 0))
    receiver.settimeout(0.2)
    try:
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
    except OSError:
        pass
    data_port = receiver.getsockname()[1]
    agg_port = free_aggregator_port()
    video_port = int(os.environ.get('FIT_LAB_RTP_PORT', '15600'))
    if not 1024 <= video_port <= 65535:
        raise ValueError('Неверный локальный RTP-порт.')
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    SOCKETS.append(sender)
    SUMMARY['local_ports'] = {'aggregator': agg_port, 'recovered_rtp': data_port, 'video_rtp': video_port}
    codec = spawn([CODEC, '-a', str(agg_port), '-K', key, '-c', '127.0.0.1', '-u', str(data_port),
                   '-i', str(LINK_ID), '-p', str(RADIO_PORT)], 'wfb-rx.log')
    time.sleep(0.4)
    if codec.poll() is not None:
        raise ValueError('wfb_rx завершился при запуске; подробности в wfb-rx.log.')

    command = [str(DIAG), '--json', '--report', str(LOGS / 'radio-report.json'), 'rx-scan',
               '--macos-usbhost', '--vid', '0x0bda', '--pid', '0x8812',
               '--init-before-rx', '--monitor-opmode-before-rx', '--rx-led', '--firmware', str(FW),
               '--channel', str(CHANNEL), '--bandwidth', str(WIDTH),
               '--duration-ms', str(DURATION_MS), '--timeout-ms', '100', '--init-timeout-ms', '500',
               '--mac-source', str(tables['mac']), '--bb-source', str(tables['bb']), '--rf-source', str(tables['rf']),
               '--cut-version', '0x00', '--package-type', '0x00',
               '--support-interface', '0x02', '--support-platform', '0x00',
               '--wfb-link-id', str(LINK_ID), '--wfb-radio-port', str(RADIO_PORT),
               '--rx-aggregator', f'127.0.0.1:{agg_port}', '--rx-mcs-index', '1',
               '--i-understand-this-writes-registers']
    for flag, value in profile.items():
        command.extend(['--' + flag, str(value)])
    help_text = run([DIAG, 'rx-scan', '--help'])
    supported = set(re.findall(r'--[a-z][a-z0-9-]*', help_text))
    missing = {p for p in command if p.startswith('--')} - supported
    if missing:
        raise ValueError('Сборка не поддерживает: ' + ', '.join(sorted(missing)))
    SUMMARY['radio_command'] = command
    SUMMARY['result'] = 'waiting_for_authenticated_rtp'
    save_summary()
    radio = spawn(command, 'radio-console.log')
    say('Инициализация → WFB-расшифровка → RTP. Ожидаю видеопакеты…')
    say(f'Приём: до {DURATION_MS // 1000} секунд. Остановка из приложения или Ctrl+C.')
    say('Светодиод горит при приёме выбранного WFB-потока; без пакетов гаснет через 1 секунду. Запись видео выключена.')
    start = last_status = time.monotonic()
    first_rtp = None
    pt = ssrc = None
    payload_types = Counter()
    sets = {}
    telemetry = RadioTelemetry(LOGS / 'wfb-rx.log')
    last_event = start
    last_rtp = None
    while time.monotonic() - start < DURATION_MS / 1000 + 120:
        if codec.poll() is not None:
            raise ValueError('wfb_rx завершился; подробности в wfb-rx.log.')
        if radio.poll() is not None:
            if radio.returncode:
                raise ValueError('Радиоприёмник завершился с ошибкой; подробности в radio-console.log.')
            break
        try:
            data, peer = receiver.recvfrom(65535)
        except socket.timeout:
            data, peer = None, None
        now = time.monotonic()
        if data and peer[0] == '127.0.0.1':
            SUMMARY['recovered_datagrams'] += 1
            rtp = parse_rtp(data)
            if rtp is None:
                SUMMARY['non_rtp_datagrams'] += 1
            else:
                packet_pt, packet_ssrc, body = rtp
                payload_types[packet_pt] += 1
                if first_rtp is None:
                    first_rtp, pt, ssrc = now, packet_pt, packet_ssrc
                    say(f'WFB-пакеты расшифрованы. Получен RTP-поток (payload type {pt}).')
                if (packet_pt, packet_ssrc) == (pt, ssrc):
                    SUMMARY['rtp_packets'] += 1
                    SUMMARY['rtp_bytes'] += len(data)
                    get_parameter_sets(body, sets)
                    sender.sendto(data, ('127.0.0.1', video_port))
                    SUMMARY['relayed_packets'] += 1
                    last_rtp = now
                    SUMMARY.update(payload_type=pt, result='rtp_received')
        if now - last_event >= 1:
            event(state='receiving' if last_rtp and now - last_rtp < 2 else 'waiting',
                  rtp_packets=SUMMARY['rtp_packets'], rtp_bytes=SUMMARY['rtp_bytes'],
                  radio=telemetry.read(), log_directory=str(LOGS))
            last_event = now
        if now - last_status >= 5:
            SUMMARY['payload_types'] = dict(payload_types)
            say(f"RTP-пакетов: {SUMMARY['rtp_packets']}; передано в приложение: {SUMMARY['relayed_packets']}; RF TX не запускался.")
            save_summary()
            last_status = now
    SUMMARY['payload_types'] = dict(payload_types)
    if radio.poll() is None:
        raise ValueError('Превышено время инициализации/приёма. Частичные результаты будут показаны.')
    time.sleep(1.1)  # Let wfb_rx flush its last statistics interval before cleanup.
    if first_rtp is None:
        raise ValueError('За время приёма RTP-видео не появилось. Счётчики — ниже.')
    SUMMARY['result'] = 'rtp_received' if first_rtp is not None else 'no_rtp'
    radio_report = LOGS / 'radio-report.json'
    if radio_report.is_file():
        report = json.loads(radio_report.read_text())
        SUMMARY['radio_counters'] = report.get('counters')
        SUMMARY['wfb_forward'] = report.get('rx_fixture', {}).get('wfb_forward')
    say('Сеанс завершён. Получение пакетов не заменяет проверку картинки в приложении.')


def summarize_codec(path):
    names = ('incoming_packets', 'incoming_bytes', 'decrypt_errors',
             'session_packets', 'data_packets', 'unique_packets',
             'fec_recovered', 'lost_packets', 'bad_packets',
             'outgoing_packets', 'outgoing_bytes')
    totals = dict.fromkeys(names, 0)
    intervals = 0
    if path.is_file():
        with path.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                match = re.search(r'\bPKT\s+([0-9]+(?::[0-9]+){10})(?:\s|$)', line)
                if match:
                    for key, value in zip(names, match.group(1).split(':')):
                        totals[key] += int(value)
                    intervals += 1
    totals['reported_intervals'] = intervals
    return totals


def collect_diagnostics():
    if LOGS is None:
        return
    say('\n=== ИТОГ ПО ВСЕЙ ЦЕПОЧКЕ ===')
    report_path = LOGS / 'radio-report.json'
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding='utf-8'))
            counters = report.get('counters') or {}
            fixture = report.get('rx_fixture') or {}
            SUMMARY['rx_activity_led'] = fixture.get('rx_activity_led')
            SUMMARY['radio_result'] = report.get('result')
            SUMMARY['radio_error'] = report.get('error')
            SUMMARY['radio_counters'] = counters
            SUMMARY['radio_rx'] = {key: fixture.get(key) for key in
                ('buffers_read', 'read_timeouts', 'bulk_bytes', 'parsed_frames',
                 'data_frames', 'management_frames', 'control_frames', 'dropped_packets')}
            SUMMARY['wfb_forward'] = fixture.get('wfb_forward')
            SUMMARY['wfb_forwards'] = fixture.get('wfb_forwards')
            say(f"Радио: result={report.get('result')}; RF-кадров={counters.get('rx_frames', 'нет поля')}; "
                f"USB-байтов={fixture.get('bulk_bytes', 'нет поля')}; таймаутов={fixture.get('read_timeouts', 'нет поля')}")
            if report.get('error'):
                say('Ошибка радиочасти: ' + json.dumps(report['error'], ensure_ascii=False))
            forward = fixture.get('wfb_forward')
            if forward is not None:
                say('WFB-фильтр/пересылка: ' + json.dumps(forward, ensure_ascii=False))
            say(f"Передача свистка по счётчикам: tx_frames={counters.get('tx_frames', 'нет поля')}; "
                f"usb_bulk_out_writes={counters.get('usb_bulk_out_writes', 'нет поля')}")
        except (OSError, ValueError, AttributeError) as exc:
            SUMMARY['report_read_error'] = str(exc)
            say('Не удалось прочитать отчёт радиочасти: ' + str(exc))
    else:
        SUMMARY['radio_report_missing'] = True
        say('Отчёт радиочасти отсутствует: процесс был прерван или не завершил инициализацию.')
    codec_stats = summarize_codec(LOGS / 'wfb-rx.log')
    SUMMARY['codec_totals'] = codec_stats
    say(f"wfb_rx за все интервалы: вход={codec_stats['incoming_packets']}; "
        f"ошибок расшифровки={codec_stats['decrypt_errors']}; "
        f"выход={codec_stats['outgoing_packets']}; "
        f"интервалов статистики={codec_stats['reported_intervals']}")
    say(f"Восстановленных UDP-пакетов={SUMMARY['recovered_datagrams']}; "
        f"RTP={SUMMARY['rtp_packets']}; не распознано как RTP/H265={SUMMARY['non_rtp_datagrams']}")
    say('Ключ не выводился. Содержимое радиопакетов в summary.json не записывается.')


if __name__ == '__main__':
    def stop_signal(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_signal)
    code = 0
    try:
        main()
    except KeyboardInterrupt:
        SUMMARY.update(result='stopped_by_user')
        say('\nОстановлено пользователем.')
    except Exception as exc:
        code = 1
        SUMMARY.update(result='error', error=str(exc))
        event(state='error', error=str(exc))
        say(f'ОШИБКА: {exc}')
    finally:
        cleanup()
        try:
            collect_diagnostics()
            save_summary()
            if LOGS is not None:
                if code:
                    for name in ('wfb-rx.log', 'radio-console.log'):
                        p = LOGS / name
                        if p.is_file() and p.stat().st_size:
                            with p.open('rb') as inp:
                                inp.seek(max(0, p.stat().st_size - 3000))
                                tail = inp.read().decode('utf-8', errors='replace').splitlines()[-5:]
                            say(f'--- {name}: последние строки ---\n' + '\n'.join(tail))
                say(f'Итог: {LOGS / "summary.json"}')
                say('Ключ остаётся на Mac. Его содержимое в отчётах отсутствует.')
        except OSError as exc:
            say(f'Не удалось сохранить итог: {exc}')
    raise SystemExit(code)
