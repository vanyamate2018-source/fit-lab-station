#!/bin/bash
# FIT-LAB dependency bootstrap for the verified ARM64 / Ubuntu 22.04 package.
set -Eeuo pipefail
PACKAGE=$(cd -- "$(dirname -- "$0")" && pwd)
MODE=${1:-install}
case "$MODE" in install|--check|--plan) ;; *) echo 'Использование: bash auto-install.sh [--check|--plan]'; exit 2;; esac
fail() { echo "НЕ ЗАВЕРШЕНО: $*" >&2; exit 1; }
stage() { printf '\n[%s] %s\n' "$1" "$2"; }
[ "$(uname -s)" = Linux ] || fail 'Запускайте этот установщик на приёмнике Linux, не на Mac.'
[ "$(uname -m)" = aarch64 ] || fail 'Комплект предназначен для ARM64 (aarch64).'
[ -r /etc/os-release ] || fail 'Не удалось определить ОС.'
. /etc/os-release
[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 22.04 ] || fail 'Эта сборка поддерживает Ubuntu 22.04 ARM64. Для другой ОС нужна отдельная сборка.'
[ "$(id -u)" != 0 ] || fail 'Запускайте от обычного пользователя. Пароль sudo будет запрошен отдельно.'
command -v apt-get >/dev/null || fail 'Не найден apt-get.'
command -v sha256sum >/dev/null || fail 'Не найден sha256sum.'
cd "$PACKAGE"
sha256sum -c application.sha256 || fail 'Повреждён или неполон установочный комплект.'
PACKAGES=(python3.10 python3-gi python3-dbus gir1.2-gstreamer-1.0
 gir1.2-gst-plugins-base-1.0 gstreamer1.0-tools gstreamer1.0-plugins-base
 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
 gstreamer1.0-x libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0
 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0
 libxcb-xinerama0 libxcb-randr0 libxcb-shape0 libxcb-xfixes0 libxcb-sync1
 libxcb-render0 libxcb-shm0 libxcb-xkb1 libdbus-1-3 libnss3 libasound2
 gnome-keyring libsecret-1-0 libsodium23 libpcap0.8 iw iproute2 network-manager
 openssh-client ca-certificates xdg-utils)
MISSING=()
for item in "${PACKAGES[@]}"; do
 [ "$(dpkg-query -W -f='${db:Status-Status}' "$item" 2>/dev/null || true)" = installed ] || MISSING+=("$item")
done
stage 1/5 'Проверка платформы и зависимостей'
printf 'Система: %s / %s\n' "$ID $VERSION_ID" "$(uname -m)"
if [ "${#MISSING[@]}" -gt 0 ]; then printf 'Нужно скачать: %s\n' "${MISSING[*]}"; else echo 'Пакеты ОС уже установлены.'; fi
RADIO=/mnt/fitlab-ssd/apps/fit-lab-receiver
READY=1
for path in /usr/local/sbin/fitlab-update /etc/systemd/system/fit-lab-receiver.service "$RADIO/wfb-source/wfb_rx" "$RADIO/wfb-source/wfb_tx"; do
 if [ ! -f "$path" ]; then echo "Требуется подготовка радиомодуля: $path"; READY=0; fi
done
if [ "$MODE" = --plan ]; then
 echo 'План: зависимости из настроенных репозиториев Ubuntu; проверка радио; установка приложения; ярлык и автозапуск.'
 echo 'Драйвер ядра, аппаратный декодер, новая карта USB и Wi-Fi не устанавливаются вслепую.'
 exit 0
fi
if [ "$MODE" = --check ]; then
 [ "$READY" = 1 ] && [ "${#MISSING[@]}" = 0 ] || exit 3
 /usr/bin/python3 -c 'import sys; assert sys.version_info[:2] == (3,10)'
 echo 'Базовые зависимости и радиомодуль присутствуют. Это не проверка совместимости нового оборудования.'
 exit 0
fi
mkdir -p "$PACKAGE/logs"
LOG="$PACKAGE/logs/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
trap 'code=$?; echo "Установка прервана (код $code). Журнал: $LOG"; exit "$code"' ERR
stage 2/5 'Загрузка недостающих компонентов'
if [ "${#MISSING[@]}" -gt 0 ]; then
 sudo -v
 sudo apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
 sudo apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends "${MISSING[@]}"
fi
/usr/bin/python3 -c 'import sys; assert sys.version_info[:2] == (3,10), "Нужен системный Python 3.10"; import gi'
stage 3/5 'Проверка радиомодуля'
[ "$READY" = 1 ] || fail 'Зависимости установлены, но новой плате нужна подготовка драйвера и радиослужбы. Приём ещё не готов.'
[ -w /mnt/fitlab-ssd/apps ] || fail 'Нет доступа на запись к SSD /mnt/fitlab-ssd/apps.'
if [ ! -d /proc/net/rtl88XXau ] && [ ! -d /proc/net/rtl88xxau_wfb ] && [ ! -d /proc/net/rtl8812au ] && [ ! -d /sys/module/88XXau_wfb ]; then
 fail 'Подключите поддерживаемые USB-приёмники. Драйвер RTL8812AU не обнаружен.'
fi
# Warm sudo credentials for the already installed maintenance helper.
sudo -v
stage 4/5 'Установка приложения и служб'
bash "$PACKAGE/install.sh"
stage 5/5 'Ярлык и автозапуск интерфейса'
DESTINATION=/mnt/fitlab-ssd/apps/fit-lab-station
mkdir -p "$HOME/.local/share/applications" "$HOME/.config/autostart"
DESKTOP="$HOME/.local/share/applications/fit-lab-station.desktop"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=FIT-LAB · Видеомодуль WFB
Exec=$DESTINATION/launch.sh
Icon=$DESTINATION/source/master/assets/app-icon.png
Terminal=false
Categories=AudioVideo;
EOF
cp "$DESKTOP" "$HOME/.config/autostart/fit-lab-station.desktop"
if command -v xdg-user-dir >/dev/null; then
 DESKTOP_DIR=$(xdg-user-dir DESKTOP)
 if [ -n "$DESKTOP_DIR" ] && [ "$DESKTOP_DIR" != "$HOME" ]; then
  mkdir -p "$DESKTOP_DIR"
  install -m 755 "$DESKTOP" "$DESKTOP_DIR/FIT-LAB.desktop"
  gio set "$DESKTOP_DIR/FIT-LAB.desktop" metadata::trusted true 2>/dev/null || true
 fi
fi
sudo loginctl enable-linger "$(id -un)"
systemctl is-active fit-lab-receiver
systemctl --user is-active fit-lab-control
printf '\nУстановка завершена. Настройки и ключи сохранены.\nЖурнал: %s\n' "$LOG"
if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
 nohup "$DESTINATION/launch.sh" >/dev/null 2>&1 </dev/null &
 echo 'Интерфейс запущен. Для видео нажмите запуск приёма.'
else
 echo 'Дисплей не обнаружен: службы работают, интерфейс откроется при входе в графическую среду.'
fi
