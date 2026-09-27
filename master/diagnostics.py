"""Small local audit records. Callers supply only public, allowed fields."""
import json
import time


def station_snapshot(state, running, usb_count):
    """Whitelist observed counters; never serialize raw camera config or credentials."""
    def pick(source, names):
        return {key: source[key] for key in names if key in source}
    radio = state.get('radio', {})
    return {'schema': 1, 'kind': 'station_snapshot', 'time': time.time(), 'running': bool(running),
            'usb_connected': usb_count,
            'audio': pick(state.get('audio', {}), ('state', 'transport', 'decoded_buffers', 'peak_db', 'muted')),
            'video': pick(state, ('phase', 'mode', 'width', 'height', 'mbps', 'fps', 'decoded_fps', 'presented_fps',
                                 'frame_age', 'pipeline_age_max_ms', 'configured_buffer_ms', 'decoder_restarts')),
            'tuning': pick(state.get('radio_tuning', {}), ('channel', 'width', 'frequency_mhz')),
            'packets': pick(radio.get('totals', {}), ('incoming_packets', 'outgoing_packets', 'fec_recovered',
                                                    'lost_packets', 'decrypt_errors', 'bad_packets')),
            'receivers': [pick(rx, ('index', 'connection', 'mac', 'rssi_dbm', 'snr_db', 'packets_per_second',
                                    'restarts', 'initializations')) for rx in state.get('receivers', [])],
            'control': pick(state.get('control', {}), ('state', 'sent', 'replies', 'rtt_ms', 'tx_receiver', 'tx_switches', 'echo_timeouts', 'echo_window_samples', 'echo_loss_percent')),
            'health': pick(state.get('health', {}), ('samples', 'status', 'fps_median', 'fps_min', 'mbps_mean',
                                                    'loss_percent', 'lost_packets', 'fec_recovered', 'decrypt_errors')),
            'end_to_end_latency_ms': None}


def append_event(root, event):
    path = root / "logs" / "station-diagnostics.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 8 * 1024 * 1024:
            path.replace(path.with_suffix(".previous.jsonl"))
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
    except (OSError, ValueError):
        # Diagnostics must never terminate reception or mask a camera result.
        pass
