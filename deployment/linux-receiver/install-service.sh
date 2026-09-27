#!/bin/bash
set -euo pipefail
[ "$(id -u)" = 0 ] || exit 1
ROOT=/mnt/fitlab-ssd/apps/fit-lab-receiver
install -d -m 755 /usr/local/libexec/fit-lab
install -m 755 "$ROOT/wfb-source/wfb_rx" /usr/local/libexec/fit-lab/wfb_rx
install -m 644 "$ROOT/forwarder.py" /usr/local/libexec/fit-lab/forwarder.py
install -m 644 "$ROOT/fit-lab-receiver.service" /etc/systemd/system/fit-lab-receiver.service
install -m 755 "$ROOT/wfb-source/wfb_tx" /usr/local/libexec/fit-lab/wfb_tx
install -m 644 "$ROOT/command_bridge.py" /usr/local/libexec/fit-lab/command_bridge.py
systemctl daemon-reload
systemctl enable fit-lab-receiver.service
systemctl restart fit-lab-receiver.service
systemctl --no-pager --full status fit-lab-receiver.service
printf '\nВидеомодуль WFB запущен. Автозапуск включён.\n'
