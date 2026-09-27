#!/bin/bash
set -euo pipefail
PACKAGE=$(cd -- "$(dirname -- "$0")" && pwd)
DESTINATION=${1:-/mnt/fitlab-ssd/apps/fit-lab-station}
case "$DESTINATION" in /*) ;; *) echo 'Нужен абсолютный путь установки'; exit 2;; esac
[ "$(uname -s)" = Linux ] || { echo 'Этот пакет предназначен для Linux'; exit 2; }
python3 -c 'import PySide6, gi' || { echo 'Установите PySide6 и python3-gi из системного комплекта'; exit 1; }
[ "$(uname -m)" = aarch64 ] || { echo "Этот комплект предназначен для ARM64"; exit 2; }
mkdir -p "$DESTINATION/releases" "$DESTINATION/data/logs" "$HOME/.local/share/applications"
RELEASE=$(date +%Y%m%d-%H%M%S)
NEXT="$DESTINATION/releases/$RELEASE"
mkdir "$NEXT"
python3 "$PACKAGE/verify.py" "$PACKAGE"
tar -xzf "$PACKAGE/source.tar.gz" -C "$NEXT"
python3 -m compileall -q "$NEXT"
if [ -f "$PACKAGE/runtime-aarch64-python310.tar.gz" ]; then
 python3 -c 'import sys; assert sys.version_info[:2] == (3,10), "Нужен Python 3.10"'
 tar -xzf "$PACKAGE/runtime-aarch64-python310.tar.gz" -C "$DESTINATION"
fi
PYTHONPYCACHEPREFIX="$DESTINATION/data/cache/python" PYTHONPATH="$DESTINATION/runtime:$NEXT" python3 -c 'import paramiko,nacl,keyring; from master.ui.main_window import MainWindow'
if [ -L "$DESTINATION/source" ]; then
 readlink "$DESTINATION/source" > "$DESTINATION/previous-release.txt"
 rm "$DESTINATION/source"
elif [ -e "$DESTINATION/source" ]; then
 mv "$DESTINATION/source" "$DESTINATION/releases/before-$RELEASE"
 printf '%s\n' "$DESTINATION/releases/before-$RELEASE" > "$DESTINATION/previous-release.txt"
fi
ln -s "$NEXT" "$DESTINATION/source"
install -m 755 "$PACKAGE/launch.sh" "$DESTINATION/launch.sh"
cat > "$HOME/.local/share/applications/fit-lab-station.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=FIT-LAB · Видеомодуль WFB
Comment=Видеомодуль WFB
Exec="$DESTINATION/launch.sh"
Icon=$DESTINATION/source/master/assets/app-icon.png
Terminal=false
Categories=AudioVideo;
DESKTOP
mkdir -p "$HOME/.config/autostart"
cp "$HOME/.local/share/applications/fit-lab-station.desktop" "$HOME/.config/autostart/fit-lab-station.desktop"
if command -v xdg-user-dir >/dev/null; then
 DESKTOP_DIR=$(xdg-user-dir DESKTOP)
 mkdir -p "$DESKTOP_DIR"
 install -m 755 "$HOME/.local/share/applications/fit-lab-station.desktop" "$DESKTOP_DIR/FIT-LAB.desktop"
 gio set "$DESKTOP_DIR/FIT-LAB.desktop" metadata::trusted true 2>/dev/null || true
fi
FIT_LAB_ROOT="$DESTINATION" PYTHONPYCACHEPREFIX="$DESTINATION/data/cache/python" \
 PYTHONPATH="$DESTINATION/runtime:$DESTINATION/source" python3 -m receiver.control_install
if loginctl --no-ask-password enable-linger "$(id -un)"; then
 printf 'Автономный запуск пользовательской службы управления после выхода включён.\n'
else
 printf 'Не удалось включить linger без дополнительных прав. Работа управления после выхода пользователя и до входа после перезагрузки не гарантирована.\n' >&2
fi
printf 'Установлено: %s\nПредыдущая версия сохранена.\n' "$DESTINATION"
