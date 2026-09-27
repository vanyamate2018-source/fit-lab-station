#!/bin/sh
# Remove only the reviewed desktop applications, not their shared dependencies.
set -eu
if [ "$(id -u)" != 0 ]; then
    echo 'Запустите через sudo: удаление установленных программ требует прав администратора.'
    exit 1
fi
apt-get remove -y audacity geany cheese qalculate-gtk redshift
# NetworkManager starts its own scoped dnsmasq for hotspot sharing. The
# unconfigured standalone daemon collides with systemd-resolved on port 53.
if ! grep -Eq '^[[:space:]]*[^#[:space:]]' /etc/dnsmasq.conf &&
   ! find /etc/dnsmasq.d -type f ! -name README ! -name '*.dpkg-*' | grep -q .; then
    systemctl disable --now dnsmasq.service
    systemctl reset-failed dnsmasq.service || true
fi
printf '%s\n' 'Удалены 5 лишних приложений. Сеть, сенсор, звук, драйверы и компоненты FIT-LAB сохранены.'
