#!/bin/bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo 'Запустите через sudo'; exit 1; }
SOURCE=$(cd -- "$(dirname -- "$0")" && pwd)
STATION_USER=${SUDO_USER:-}
[[ "$STATION_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo 'Устанавливайте через sudo от пользователя приложения'; exit 1; }
install -o root -g root -m 755 "$SOURCE/hotspot-helper.sh" /usr/local/sbin/fitlab-hotspot
RULE=$(mktemp)
trap 'rm -f "$RULE"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/fitlab-hotspot start, /usr/local/sbin/fitlab-hotspot stop\n' "$STATION_USER" > "$RULE"
visudo -cf "$RULE"
install -o root -g root -m 440 "$RULE" /etc/sudoers.d/fitlab-hotspot
echo 'Установлено управление только точкой доступа FIT-LAB. Другие команды sudo не разрешены.'
