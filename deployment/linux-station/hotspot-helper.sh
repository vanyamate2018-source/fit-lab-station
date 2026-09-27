#!/bin/bash
# Root-owned, fixed-purpose reset for AP6256/bcmdhd warm AP restart failure.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
[ "$#" = 1 ] || exit 2
case "$1" in start|stop) ;; *) exit 2;; esac
[ "$(id -u)" = 0 ] || exit 1
exec 9>/run/lock/fitlab-hotspot.lock
flock -w 30 9
PROFILE='FIT-LAB WFB'
DEVICE=wlan0
if [ "$1" = stop ]; then
 active=$(nmcli -g GENERAL.CONNECTION device show "$DEVICE" 2>/dev/null || true)
 [ "$active" != "$PROFILE" ] || nmcli --wait 10 device disconnect "$DEVICE" >/dev/null
 exit 0
fi
[ "$(nmcli -g 802-11-wireless.mode connection show "$PROFILE")" = ap ]
[ "$(nmcli -g connection.interface-name connection show "$PROFILE")" = "$DEVICE" ]
[ -d /sys/module/bcmdhd ] || { echo 'Не найден встроенный драйвер Wi-Fi'; exit 1; }
active=$(nmcli -g GENERAL.CONNECTION device show "$DEVICE" 2>/dev/null || true)
if [ "$active" = "$PROFILE" ]; then
 nmcli -g IP4.ADDRESS device show "$DEVICE"
 exit 0
fi
# Only onboard Broadcom; WFB uses independent USB drivers and Ethernet stays up.
[ "$(basename "$(readlink -f /sys/class/net/$DEVICE/device/driver)")" = bcmsdh_sdmmc ] || { echo 'Другой Wi-Fi драйвер'; exit 1; }
nmcli device disconnect "$DEVICE" >/dev/null 2>&1 || true
modprobe -r bcmdhd
modprobe bcmdhd
ready=0
for n in $(seq 1 40); do
 state=$(LC_ALL=C nmcli -g GENERAL.STATE device show "$DEVICE" 2>/dev/null || true)
 case "$state" in 30*|100*) ready=1; break;; esac
 sleep .5
done
[ "$ready" = 1 ] || { echo 'Wi-Fi не восстановился после перезапуска'; exit 1; }
if ! nmcli --wait 20 connection up "$PROFILE" >/dev/null; then
 nmcli device disconnect "$DEVICE" >/dev/null 2>&1 || true
 exit 1
fi
nmcli -g IP4.ADDRESS device show "$DEVICE"
