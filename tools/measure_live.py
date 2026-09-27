"""Observe station telemetry without touching the camera or radio pipeline."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import time


def latest(path):
    with path.open('rb') as stream:
        stream.seek(max(0, stream.seek(0, 2) - 65536))
        lines = stream.read().splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--warmup', type=int, default=10)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 600 or not 0 <= args.warmup <= 60:
        parser.error('invalid measurement duration')
    source = Path('/Volumes/FIT-LAB/data/telemetry/master-video.jsonl')
    begin = time.time() + args.warmup
    rows, seen = [], set()
    while time.time() < begin + args.seconds:
        try:
            row = latest(source)
            stamp = row.get('time', 0)
            if stamp >= begin and stamp not in seen:
                seen.add(stamp)
                rows.append(row)
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    if len(rows) < 2:
        raise RuntimeError('No fresh station telemetry')
    first, last = rows[0], rows[-1]
    sessions = {row.get('log_directory') for row in rows}
    if len(sessions) != 1:
        raise RuntimeError('Receiver restarted during measurement; repeat after startup')
    def values(key):
        return [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    def median(key):
        samples = values(key)
        return round(statistics.median(samples), 3) if samples else None
    before, after = first.get('radio', {}).get('totals', {}), last.get('radio', {}).get('totals', {})
    counts = {key: after.get(key, 0) - before.get(key, 0) for key in
              ('incoming_packets', 'outgoing_packets', 'fec_recovered', 'lost_packets', 'decrypt_errors')}
    total = counts['outgoing_packets'] + counts['lost_packets']
    report = dict(started=first['time'], ended=last['time'], samples=len(rows),
                  log_directory=last.get('log_directory'), phase_samples=dict(Counter(row['phase'] for row in rows)),
                  decoded_size=[last.get('width'), last.get('height')],
                  radio_tuning=last.get('radio_tuning'),
                  recovery_mode=last.get('recovery_mode'), fps_median=median('fps'),
                  decoded_fps_median=median('decoded_fps'), rtp_fps_median=median('rtp_fps'),
                  presented_fps_median=median('presented_fps'), paint_max_ms=max(values('paint_max_ms'), default=None),
                  configured_buffer_ms=last.get('configured_buffer_ms'),
                  fps_min=min(values('fps'), default=None), mbps_median=median('mbps'),
                  pipeline_age_max_ms_median=median('pipeline_age_max_ms'),
                  pipeline_age_max_ms=max(values('pipeline_age_max_ms'), default=None),
                  decoder_to_ui_ms_median=median('decoder_to_ui_ms'),
                  frame_age_max=max(values('frame_age'), default=None), counts=counts,
                  loss_percent=round(100 * counts['lost_packets'] / total, 4) if total else None,
                  tx_states=dict(Counter(row.get('control', {}).get('state') for row in rows)),
                  tx_last=last.get('control'), end_to_end_latency_ms=None)
    profiles = {json.dumps({key: row.get(key) for key in ('width', 'height', 'radio_tuning')},
                           sort_keys=True) for row in rows if row.get('phase') == 'video'}
    report['observed_video_profiles'] = [json.loads(item) for item in sorted(profiles)]
    report['mixed_video_profiles'] = len(profiles) > 1
    report['receiver_restarts'] = [last['receivers'][i].get('restarts', 0) - first['receivers'][i].get('restarts', 0)
                                  for i in range(min(len(last.get('receivers', [])), len(first.get('receivers', []))))]
    before_drops, after_drops = first.get('jitter_drop_events', {}), last.get('jitter_drop_events', {})
    report['local_rtp_drop_events'] = {reason: count - before_drops.get(reason, 0)
                                       for reason, count in after_drops.items()}
    report['decoder_restarts'] = last.get('decoder_restarts', 0) - first.get('decoder_restarts', 0)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
