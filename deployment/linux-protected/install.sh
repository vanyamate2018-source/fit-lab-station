#!/bin/bash
set -euo pipefail
PACKAGE=$(cd -- "$(dirname -- "$0")" && pwd)
DESTINATION=${1:-/mnt/fitlab-ssd/apps/fit-lab-station}
[ "$(uname -m)" = aarch64 ] || { echo 'Нужен Linux ARM64'; exit 2; }
cd "$PACKAGE"
sha256sum -c application.sha256
python3 -c 'import sys; assert sys.version_info[:2] == (3,10), "Нужен Python 3.10"'
mkdir -p "$DESTINATION"
if [ ! -d "$DESTINATION/runtime" ] && [ -f "$PACKAGE/runtime-aarch64-python310.tar.gz" ]; then
 tar --no-same-owner -xzf "$PACKAGE/runtime-aarch64-python310.tar.gz" -C "$DESTINATION"
fi
RELEASE="$DESTINATION/releases/installed-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RELEASE"
python3 - "$PACKAGE/application.tar.gz" "$RELEASE" <<'PY'
import hashlib,json,sys,tarfile
from pathlib import Path
archive,destination=sys.argv[1],Path(sys.argv[2])
with tarfile.open(archive) as stream:
 for member in stream.getmembers():
  path=Path(member.name)
  if not member.isfile() or path.is_absolute() or '..' in path.parts or path.suffix == '.py':
   raise SystemExit('Недопустимый файл установщика')
  target=destination/path;target.parent.mkdir(parents=True,exist_ok=True)
  target.write_bytes(stream.extractfile(member).read())
manifest=json.loads((destination/'release.json').read_text())
for name,digest in manifest['files'].items():
 if hashlib.sha256((destination/name).read_bytes()).hexdigest()!=digest:raise SystemExit('Неверная контрольная сумма')
print('Файлы приложения проверены; открытых Python-исходников нет')
PY
FIT_LAB_ROOT="$DESTINATION" FIT_LAB_DATA_ROOT="$DESTINATION/data" FIT_LAB_EMBEDDED_RECEIVER=1 \
 PYTHONPATH="$DESTINATION/runtime:$RELEASE" python3 -c 'from master.ui.main_window import MainWindow; import receiver.control_service; import shared.master_presence'
# Stop only this user's station GUI; persistent RF forwarding stays independent.
PIDS=$(pgrep -u "$(id -u)" -f '^/usr/bin/python3 -m master.gui( |$)' || true)
if [ -n "$PIDS" ]; then
 kill -TERM $PIDS
 for attempt in $(seq 1 25); do
  remaining=0
  for pid in $PIDS; do kill -0 "$pid" 2>/dev/null && remaining=1; done
  [ "$remaining" = 0 ] && break
  sleep 1
 done
 for pid in $PIDS; do
  if kill -0 "$pid" 2>/dev/null; then echo 'Приложение ещё завершает работу; установка не активирована'; exit 1; fi
 done
fi
systemctl --user stop fit-lab-control.service
python3 - "$DESTINATION" "$RELEASE" <<'PY'
from pathlib import Path
import os,sys
home,release=map(Path,sys.argv[1:])
current=home/'source'
if current.is_symlink():(home/'previous-release.txt').write_text(str(current.resolve()))
link=home/'source.next'
link.unlink(missing_ok=True);link.symlink_to(release)
os.replace(link,current)
PY
install -m 755 "$PACKAGE/launch.sh" "$DESTINATION/launch.sh"
install -d "$DESTINATION/tools"
install -m 755 "$PACKAGE/wfb-radio-ssh" "$DESTINATION/tools/wfb-radio-ssh.next"
mv "$DESTINATION/tools/wfb-radio-ssh.next" "$DESTINATION/tools/wfb-radio-ssh"
FIT_LAB_ROOT="$DESTINATION" PYTHONPATH="$DESTINATION/runtime:$DESTINATION/source" python3 -m receiver.control_install
# Update the radio helpers on an already provisioned receiver.
RADIO_HOME=/mnt/fitlab-ssd/apps/fit-lab-receiver
if [ -x /usr/local/sbin/fitlab-update ] && [ -d "$RADIO_HOME" ]; then
 if [ -f "$PACKAGE/wfb_rx" ]; then
  install -m 755 "$PACKAGE/wfb_rx" "$RADIO_HOME/wfb-source/wfb_rx.next"
  mv "$RADIO_HOME/wfb-source/wfb_rx.next" "$RADIO_HOME/wfb-source/wfb_rx"
 fi
 for helper in forwarder command_bridge; do
  install -m 644 "$PACKAGE/$helper.pyc" "$RADIO_HOME/$helper.py"
 done
 sudo -n /usr/local/sbin/fitlab-update
else
 echo 'Радиомодуль требует первичной установки системных компонентов.'
fi
# Keep the receiver desktop quiet; FIT-LAB uses its own notifications.
if command -v xfconf-query >/dev/null 2>&1; then
 while read -r channel property value; do
  if xfconf-query -c "$channel" -p "$property" >/dev/null 2>&1; then
   xfconf-query -c "$channel" -p "$property" -s "$value" || echo "Не применена настройка рабочего стола: $property"
  else
   xfconf-query -c "$channel" -p "$property" --create -t bool -s "$value" || echo "Не применена настройка рабочего стола: $property"
  fi
 done <<'DESKTOP_SETTINGS'
xfce4-notifyd /do-not-disturb true
xsettings /Gtk/EnableTooltips false
xfce4-desktop /desktop-icons/show-tooltips false
DESKTOP_SETTINGS
fi
printf 'FIT-LAB установлен. Настройки и ключи сохранены.\n'
