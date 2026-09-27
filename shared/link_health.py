"""Observed short-window link health, never an estimate of glass-to-glass delay."""
from collections import deque
from statistics import median


class LinkHealth:
    def __init__(self):
        self.samples = deque(maxlen=30)
        self.previous = None

    def add(self, state):
        totals = state.get("radio", {}).get("totals", {})
        names = ("lost_packets", "fec_recovered", "decrypt_errors", "outgoing_packets")
        current = {name: int(totals.get(name, 0)) for name in names}
        # A new receiver session resets counters; never invent negative losses.
        delta = {name: max(0, current[name] - self.previous[name]) if self.previous else 0 for name in names}
        self.previous = current
        age = state.get("frame_age")
        fresh = age is not None and age < 2 and state.get("phase") == "video"
        self.samples.append({**delta, "mbps": state.get("mbps", 0), "fps": state.get("fps", 0) if fresh else 0,
                             "video": fresh})
        lost = sum(row["lost_packets"] for row in self.samples)
        delivered = sum(row["outgoing_packets"] for row in self.samples)
        errors = sum(row["decrypt_errors"] for row in self.samples)
        rx = [{"rx": int(item.get("index", index)) + 1, "state": item.get("connection"),
               "rssi_dbm": item.get("rssi_dbm"), "snr_db": item.get("snr_db"), "restarts": item.get("restarts", 0)}
              for index, item in enumerate(state.get("receivers", []))]
        return {"samples": len(self.samples), "mbps_mean": round(sum(row["mbps"] for row in self.samples) / len(self.samples), 2),
                "fps_median": round(median(row["fps"] for row in self.samples), 1),
                "fps_min": min(row["fps"] for row in self.samples), "lost_packets": lost,
                "fec_recovered": sum(row["fec_recovered"] for row in self.samples),
                "decrypt_errors": errors, "loss_percent": round(100 * lost / (delivered + lost), 3) if delivered + lost else None,
                "video_samples": sum(row["video"] for row in self.samples), "receivers": rx,
                "status": "no_video" if not fresh else "losses" if lost or errors else "receiving",
                "end_to_end_latency_ms": None}


def health_text(result):
    loss = result["loss_percent"]
    def receiver_text(item):
        if item['state'] != 'receiving':
            return f"RX{item['rx']} {item['state']}"
        text = f"RX{item['rx']} {item['rssi_dbm']} dBm"
        if item.get('snr_db') is not None:
            text += f" / SNR {item['snr_db']} dB"
        return text
    receivers = '; '.join(receiver_text(item) for item in result['receivers'])
    return (f"Приём · {result['mbps_mean']:.2f} Мбит/с · FPS {result['fps_median']:g} (мин. {result['fps_min']:g}) · "
            f"потери {loss if loss is not None else '—'}% · FEC {result['fec_recovered']} · "
            f"ошибки расшифровки {result['decrypt_errors']} · {receivers}")
