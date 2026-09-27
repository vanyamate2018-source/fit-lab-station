"""Radio values are separate from the Majestic video configuration."""
import re

CHANNELS = tuple(range(1, 15)) + tuple(range(36, 65, 4)) + tuple(range(100, 145, 4)) + (149, 153, 157, 161, 165)


def frequency(channel):
    if type(channel) is not int or channel not in CHANNELS:
        raise ValueError("Канал не поддерживается приёмником")
    return 2484 if channel == 14 else 2407 + 5 * channel if channel < 14 else 5000 + 5 * channel


def receiver_settings(channel=161, width=20):
    frequency(channel)
    if type(width) is not int or width not in (20, 40):
        raise ValueError("Поддерживается полоса 20 или 40 МГц")
    return {"channel": channel, "width": width, "frequency_mhz": frequency(channel)}


def live_interface(text):
    result = {}
    match = re.search(r"channel (\d+) \((\d+) MHz\).*?width: (\d+) MHz", text)
    if match:
        result.update(channel=int(match[1]), frequency_mhz=int(match[2]), width=int(match[3]))
    power = re.search(r"txpower ([-\d.]+) dBm", text)
    if power:
        result["driver_dbm"] = float(power[1])
    return result


def available_channels(text):
    result = []
    for line in text.splitlines():
        found = re.search(r"\* (\d+) MHz \[(\d+)\]", line)
        if not found or any(word in line.lower() for word in ("disabled", "no ir", "radar", "passive")):
            continue
        mhz, channel = map(int, found.groups())
        if channel in CHANNELS and frequency(channel) == mhz:
            result.append(channel)
    return sorted(set(result), key=frequency)


def channel_power_limits(text):
    allowed = set(available_channels(text))
    limits = {}
    for line in text.splitlines():
        match = re.search(r"\* \d+ MHz \[(\d+)\] \(([\d.]+) dBm\)", line)
        if match and int(match[1]) in allowed and 0 < float(match[2]) <= 40:
            limits[int(match[1])] = float(match[2])
    return limits


def working_band(frequency_mhz):
    if type(frequency_mhz) not in (int, float):
        return None
    if 2400 <= frequency_mhz < 2500:
        return '2.4'
    if 5000 <= frequency_mhz < 5900:
        return '5'
    return None


def same_band_channels(channels, live):
    """A dual-band driver does not prove a dual-band PA or antenna."""
    band = working_band(live.get('frequency_mhz'))
    if band is None:
        return []
    return [c for c in channels if c != 14 and working_band(frequency(c)) == band]


def power_value(dbm, snapshot, channel):
    """Only the positively identified EU half-dBm mapping is writable."""
    maximum = snapshot.get("power_limits", {}).get(channel)
    if maximum is None:
        maximum = snapshot.get("power_limits", {}).get(str(channel))
    if snapshot.get("power_scale") != .5 or maximum is None or type(dbm) not in (int, float):
        raise ValueError("Камера не сообщила диапазон мощности")
    if not 0 <= dbm <= maximum or not float(dbm * 2).is_integer():
        raise ValueError("Мощность вне диапазона камеры или не кратна 0,5 dBm")
    step = snapshot.get('power_step', .5)
    if not float(dbm / step).is_integer():
        raise ValueError(f'Драйвер подтверждает мощность с шагом {step:g} dBm')
    return int(dbm * 2)


def diagnose(config, live, adaptive=False, backend="unknown"):
    messages = []
    if backend == "unknown":
        messages.append("Формат радиослужбы не определён")
    if config.get("channel") is not None and live.get("channel") is not None and config["channel"] != live["channel"]:
        messages.append(f"Сохранён канал {config['channel']}, работает {live['channel']}")
    if config.get("width") is not None and live.get("width") is not None and config["width"] != live["width"]:
        messages.append("Сохранённая полоса ещё не применена")
    if adaptive:
        messages.append("ALink управляет параметрами автоматически")
    return messages


# Manufacturer reference; never use this table as driver readback or a limit.
RUNCAM_WIFILINK2_POWER = {
    20: (16, 40), 25: (20, 100), 30: (22, 160), 35: (24, 250),
    40: (26, 400), 45: (27, 500), 50: (28, 630), 55: (28.5, 700), 58: (29, 800),
}


def runcam_power_reference(snapshot):
    """Exact table points only; vendor firmware does not establish board model."""
    if not snapshot.get('vendor_managed') or snapshot.get('driver') != 'rtl88x2eu':
        return None
    value = snapshot.get('config', {}).get('power')
    if type(value) is not int or value not in RUNCAM_WIFILINK2_POWER:
        return None
    dbm, mw = RUNCAM_WIFILINK2_POWER[value]
    return {'profile': 'RunCam WiFiLink 2', 'value': value, 'dbm': dbm, 'mw': mw,
            'source': 'https://support.runcam.com/hc/en-us/articles/31336740223895-What-output-power-does-WiFiLink-2-support'}


def power_choices(snapshot, channel):
    """Display vendor reference without changing validated driver command units."""
    maximum = snapshot.get('power_limits', {}).get(channel, snapshot.get('power_limits', {}).get(str(channel)))
    step = snapshot.get('power_step', .5)
    if snapshot.get('power_scale') != .5 or not isinstance(maximum, (int, float)) or not 0 < step <= 1 or not 0 <= maximum <= 40:
        return []
    items = []
    for index in range(int(maximum / step) + 1):
        value = index * step
        raw = power_value(value, snapshot, channel)
        reference = runcam_power_reference({**snapshot, 'config': {'power': raw}})
        if snapshot.get('vendor_managed') and snapshot.get('driver') == 'rtl88x2eu' and reference is None and raw != snapshot.get('config', {}).get('power'):
            continue
        title = (f"≈{reference['mw']} мВт · RunCam" if reference else f"{value:g} dBm · драйвер")
        items.append((title, value))
    return items
