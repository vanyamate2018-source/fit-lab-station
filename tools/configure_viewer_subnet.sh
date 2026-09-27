#!/bin/zsh
# Administrator-run, one-shot setup using Apple's signed configuration utility.
# Never print or copy the Wi-Fi credential dictionary to the diagnostic log.
set -eu
prefs=/Library/Preferences/SystemConfiguration/com.apple.nat.plist
if [[ $EUID -ne 0 ]]; then
    print -u2 'Для настройки требуется запуск через sudo.'
    exit 1
fi
enabled=$(/usr/bin/plutil -extract NAT.Enabled raw -o - "$prefs")
if [[ "$enabled" != 0 ]]; then
    print -u2 'Сначала выключите Общий интернет в Системных настройках.'
    exit 2
fi
/usr/sbin/scutil --prefs com.apple.nat.plist <<'SCUTIL'
get /NAT
d.add SharingNetworkNumberStart 192.168.50.0
d.add SharingNetworkNumberEnd 192.168.50.254
d.add SharingNetworkMask 255.255.255.0
set /NAT
commit
apply
quit
SCUTIL
for item in SharingNetworkNumberStart SharingNetworkNumberEnd SharingNetworkMask; do
    expected=192.168.50.0
    [[ "$item" = SharingNetworkNumberEnd ]] && expected=192.168.50.254
    [[ "$item" = SharingNetworkMask ]] && expected=255.255.255.0
    actual=$(/usr/bin/plutil -extract "NAT.$item" raw -o - "$prefs")
    if [[ "$actual" != "$expected" ]]; then
        print -u2 "Проверка не пройдена: $item не сохранён."
        exit 3
    fi
done
print 'FIT-LAB: подсеть раздачи 192.168.50.0/24 сохранена и проверена.'
