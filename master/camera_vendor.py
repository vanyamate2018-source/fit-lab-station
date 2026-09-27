"""Minimal RunCam user.ini updates; private values never leave the camera."""
import re
import shlex

PATHS = ("/etc/user.ini", "/mnt/mmcblk0p1/user.ini")
KEYS = {"channel", "txpower", "mcs_index", "codec", "Size", "fps", "bitrate",
        "mirror", "flip", "rotate", "contrast", "hue", "saturation", "luminance"}
SETTING_KEYS = {"video0.codec": "codec", "video0.size": "Size", "video0.fps": "fps", "video0.bitrate": "bitrate",
                **{"image." + key: key for key in ("mirror", "flip", "rotate", "contrast", "hue", "saturation", "luminance")}}


def parse_values(text):
    values = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\s*([A-Za-z_]+)\s*=\s*([A-Za-z0-9.-]+)\s*(?:[#;].*)?", line)
        if not match or match[1] not in KEYS or match[1] in values:
            raise ValueError("Неоднозначный формат настроек RunCam")
        values[match[1]] = match[2]
    return values


def read_ini(client):
    from master.camera_radio import command_sections
    result = {}
    pattern = "|".join(sorted(KEYS))
    commands = []
    for path in PATHS:
        commands.extend(["test -f " + path,
                         "awk -F= '$1 ~ /^[[:space:]]*(" + pattern + ")[[:space:]]*$/ {print}' " + path,
                         "sha256sum " + path])
    replies = command_sections(client, commands)
    for index, path in enumerate(PATHS):
        (code, _), (values_code, selected), (hash_code, digest) = replies[index * 3:index * 3 + 3]
        if code:
            continue
        if values_code:
            raise ValueError("Не удалось прочитать настройки RunCam")
        values = parse_values(selected)
        digest = digest.split()[0] if digest else ""
        if hash_code or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Камера не подтвердила контрольную сумму настроек")
        result[path] = {"values": values, "digest": digest}
    return result


def update_script(path, observed, changes):
    if path not in PATHS or not re.fullmatch(r"[a-f0-9]{64}", observed.get("digest", "")):
        raise ValueError("Неизвестный файл RunCam")
    rules = []
    for key, value in changes.items():
        if key not in KEYS or key not in observed["values"]:
            raise ValueError("Настройка отсутствует в user.ini: " + key)
        if not re.fullmatch(r"[A-Za-z0-9.-]+", value):
            raise ValueError("Неверное значение настройки RunCam")
        if value == observed["values"][key]:
            continue
        rules.append('/^[ \\t]*' + key + '[ \\t]*=/ {match($0, /=[ \\t]*/); prefix=substr($0,1,RSTART+RLENGTH-1); tail=substr($0,RSTART+RLENGTH); sub(/^[A-Za-z0-9.-]+/, "' + value + '", tail); $0=prefix tail}')
    awk = "\n".join(rules + ["{print}"])
    # Rewrite on-device and compare the original hash again immediately before
    # rename. Unrelated lines, including any secrets, are neither read back nor
    # reconstructed by FIT-LAB. Only the temporary file is removed by the trap.
    return '\n'.join([
        "set -eu", "cfg=" + shlex.quote(path), "expected=" + shlex.quote(observed["digest"]),
        'test "$(sha256sum "$cfg" | cut -d " " -f 1)" = "$expected"',
        'tmp=$(mktemp "${cfg}.fitlab.XXXXXX")', 'trap \'rm -f "$tmp"\' EXIT HUP INT TERM',
        'cp -p "$cfg" "$tmp"', 'awk ' + shlex.quote(awk) + ' "$cfg" > "$tmp"',
        'test "$(sha256sum "$cfg" | cut -d " " -f 1)" = "$expected"',
        'mv -f "$tmp" "$cfg"', 'trap - EXIT HUP INT TERM', 'sync',
    ])


def write_ini(client, observed, changes):
    from master.camera_radio import command
    # Validate every file before the first mutation. A format change never
    # causes a guessed key to be inserted into a vendor configuration.
    scripts = [update_script(path, data, changes) for path, data in observed.items()]
    if not scripts:
        raise ValueError("Файл настроек RunCam не найден")
    for script in scripts:
        code, detail = command(client, "sh -c " + shlex.quote(script) + " 2>&1", timeout=20)
        if code:
            raise ValueError("RunCam не подтвердил запись user.ini (код " + str(code) + "). " + detail[:300])
    result = read_ini(client)
    if set(result) != set(observed) or any(result[path]["values"].get(key) != value for path in observed for key, value in changes.items()):
        raise ValueError("RunCam не подтвердил сохранённые значения user.ini")
    return result
