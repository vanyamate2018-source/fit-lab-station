#!/bin/bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo 'Запустите через sudo'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
# Explicit desktop tools only. No autoremove: keep shared graphics/media/input libraries.
apt-get remove -y gnuradio gparted gnome-system-monitor lxtask evince
# Remove the unused second browser; Chromium remains for local viewer checks.
if command -v snap >/dev/null && snap list firefox >/dev/null 2>&1; then
 snap remove firefox
fi
if ! grep -Eq '^[[:space:]]*[^#[:space:]]' /etc/dnsmasq.conf &&
   ! find /etc/dnsmasq.d -type f ! -name README ! -name '*.dpkg-*' | grep -q .; then
 systemctl disable --now dnsmasq.service
 systemctl reset-failed dnsmasq.service || true
fi
# Refresh metadata only; never replace the validated board kernel/video stack here.
apt-get update
apt list --upgradable 2>/dev/null > /mnt/fitlab-ssd/apps/fit-lab-station/data/logs/available-updates.txt
printf '%s\n' 'Очистка завершена. Список обновлений сохранён; ядро и драйверы не обновлялись.'
