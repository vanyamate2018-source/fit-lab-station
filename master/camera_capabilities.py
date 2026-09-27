"""Device assessment from authenticated observations, never model-name guesses."""
import re
import time

from shared.radio_settings import frequency


def assess(values, radio=None, settings=None):
    radio = radio or {}
    channels = radio.get('channels', [])
    reported = radio.get('reported_channels', channels)
    mhz = [frequency(c) for c in reported]
    bands = []
    if any(2400 <= f < 2500 for f in mhz):
        bands.append('2,4 ГГц')
    if any(5000 <= f < 5900 for f in mhz):
        bands.append('5 ГГц')
    config = (settings or {}).get('config', {})
    supported = bool(values.get('cli') and values.get('majestic') and values.get('codec') in ('h264', 'h265'))
    controls = []
    if supported and settings:
        controls.append('video.parameters.read')
        controls.append('video.parameters.write')
    if supported and radio.get('restart_ready'):
        controls += ['radio.parameters.read', 'radio.restart']
        if channels and not radio.get('adaptive'):
            controls.append('radio.frequency.write')
        if radio.get('power_scale') and radio.get('power_limits') and not radio.get('adaptive'):
            controls.append('radio.power.write')
    return dict(schema=1, checked_at=time.time(), adapter='openipc_ssh' if supported else None,
                compatibility='supported' if supported and settings else 'partial' if supported else 'unsupported',
                capabilities=controls, bands=bands, channels=channels,
                frequency_range_mhz=[min(mhz), max(mhz)] if mhz else [],
                active_frequency_mhz=radio.get('live', {}).get('frequency_mhz'),
                working_band=radio.get('working_band'), transmitter=radio.get('hardware', {}),
                transmitter_identity=radio.get('hardware_id'),
                radio_verified=bool(channels), power_limits=radio.get('power_limits', {}),
                authentication_enabled=config.get('system', {}).get('unsafe') is False,
                model=values.get('hostname', ''), sensor=values.get('sensor', ''),
                firmware=values.get('firmware', ''), notices=radio.get('notices', []))


def summary(assessment):
    a = assessment or {}
    labels = {'supported': 'Совместима', 'partial': 'Частично проверена', 'unsupported': 'Нужен другой драйвер'}
    bands = ' + '.join(a.get('bands', [])) or 'Диапазон не подтверждён'
    interval = a.get('frequency_range_mhz', [])
    if len(interval) == 2:
        bands += f' · {interval[0]}–{interval[1]} МГц'
    tx = a.get('transmitter', {})
    transmitter = ('USB · ' + tx.get('manufacturer', '') + ' ' + tx.get('product', '')).strip() if tx.get('idVendor') else 'Не определён'
    return {'compatibility': labels.get(a.get('compatibility'), 'Не проверена'), 'radio_bands': bands,
            'transmitter': transmitter, 'working_band': {'2.4': '2,4 ГГц', '5': '5 ГГц'}.get(a.get('working_band'), 'Не подтверждён'),
            'active_frequency': f"{a['active_frequency_mhz']} МГц" if a.get('active_frequency_mhz') else '—'}
