#!/bin/bash
set -euo pipefail
[ "$(id -u)" = 0 ] || exit 1
cat > /usr/local/sbin/fitlab-update <<'HELPER'
#!/bin/bash
set -euo pipefail
[ "$#" = 0 ] || exit 2
ROOT=/mnt/fitlab-ssd/apps/fit-lab-receiver
/usr/bin/install -d -m 755 /usr/local/libexec/fit-lab
for binary in wfb_rx wfb_tx; do
 /usr/bin/install -o root -g root -m 755 "$ROOT/wfb-source/$binary" "/usr/local/libexec/fit-lab/$binary"
done
for script in forwarder.py command_bridge.py; do
 /usr/bin/install -o root -g root -m 644 "$ROOT/$script" "/usr/local/libexec/fit-lab/$script"
done
/usr/bin/systemctl restart fit-lab-receiver.service
/usr/bin/systemctl is-active fit-lab-receiver.service
HELPER
chown root:root /usr/local/sbin/fitlab-update
chmod 755 /usr/local/sbin/fitlab-update
TEMP=$(mktemp)
trap 'rm -f "$TEMP"' EXIT
printf 'orangepi ALL=(root) NOPASSWD: /usr/local/sbin/fitlab-update ""\n' > "$TEMP"
visudo -cf "$TEMP"
install -o root -g root -m 440 "$TEMP" /etc/sudoers.d/fitlab-maintenance
printf '\nОбновление FIT-LAB настроено. Остальные команды sudo требуют пароль.\n'
