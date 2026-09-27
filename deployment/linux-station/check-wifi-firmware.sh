#!/bin/bash
# Test only the built-in Broadcom AP firmware. Never touch Ethernet or USB RX.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Запустите через sudo'; exit 1; }
PROFILE='FIT-LAB WFB'
FW='/lib/firmware/fw_bcm43456c5_ag_apsta.bin'
[ -f "$FW" ] && [ -d /sys/module/bcmdhd ] || { echo 'Этот Wi-Fi модуль не поддерживается проверкой'; exit 1; }
OLD=$(cat /sys/module/bcmdhd/parameters/firmware_path)
RESULT=/mnt/fitlab-ssd/apps/fit-lab-station/data/logs/wifi-firmware-check.log
exec > >(tee "$RESULT") 2>&1
restored=0
restore() {
 nmcli device disconnect wlan0 >/dev/null 2>&1 || true
 if [ "$restored" = 0 ]; then
  modprobe -r bcmdhd || return
  if [ -n "$OLD" ]; then modprobe bcmdhd firmware_path="$OLD"; else modprobe bcmdhd; fi
  restored=1
 fi
}
trap restore EXIT
echo 'Проверка встроенного Wi-Fi. Проводная сеть и USB RX сохраняются.'
nmcli device disconnect wlan0 >/dev/null 2>&1 || true
modprobe -r bcmdhd
modprobe bcmdhd firmware_path="$FW"
for n in $(seq 1 20); do [ -e /sys/class/net/wlan0 ] && break; sleep .5; done
nmcli device set wlan0 managed yes
sleep 2
if nmcli --wait 20 connection up "$PROFILE"; then
 echo 'AP_FIRMWARE_OK'
 nmcli -g IP4.ADDRESS device show wlan0
else
 echo 'AP_FIRMWARE_FAILED — восстанавливаю исходный драйвер'
 exit 1
fi
# Test only: restore the original firmware; permanent activation is a separate step.
restore
trap - EXIT
echo 'Проверка завершена; исходная прошивка восстановлена.'
