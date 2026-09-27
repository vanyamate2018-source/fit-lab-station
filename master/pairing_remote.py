"""Camera watchdog. Key bytes travel through SSH stdin, never argv."""
import shlex

BASE = '/etc/fit-lab-pairing'
KEY = '/etc/drone.key'
BOOT = '/etc/init.d/S97fitlab-pairing'

RESTART = '''
for name in wfb_rx wfb_tx wfb_tun msposd mavfwd wifilink; do
  for pid in $(pidof "$name"); do
    [ "$(cat /proc/$pid/comm 2>/dev/null)" = "$name" ] && kill -TERM "$pid" 2>/dev/null
  done
done
attempt=0
while pidof wfb_rx wfb_tx wfb_tun msposd mavfwd wifilink >/dev/null; do
  attempt=$((attempt+1)); [ "$attempt" -lt 40 ] || return 1
  sleep 0.1
done
setsid timeout 8 wifibroadcast start </dev/null >/dev/null 2>&1 9>&-
'''


def boot_script(base=BASE, key=KEY):
    return f'''#!/bin/sh
[ "$1" = start ] || exit 0
base={shlex.quote(base)}
[ -f "$base/pending" ] || exit 0
id=$(cat "$base/pending")
case "$id" in *[!0-9a-f]*|'') exit 1;; esac
[ "${{#id}}" = 32 ] || exit 1
op="$base/$id"
[ "$(cat "$op/status" 2>/dev/null)" = committed ] && exit 0
[ -f "$op/previous.key" ] && [ "$(wc -c < "$op/previous.key")" -eq 64 ] || exit 1
umask 077
cp "$op/previous.key" {shlex.quote(key + '.fitlab.tmp')} &&
chmod 600 {shlex.quote(key + '.fitlab.tmp')} &&
mv {shlex.quote(key + '.fitlab.tmp')} {shlex.quote(key)} || exit 1
sync
echo rolled_back > "$op/status"
rm -f "$base/pending"
sync
'''


def activation_script(ticket, preflight='', *, base=BASE, key=KEY, restart=RESTART, ticks=900):
    from shared.pairing_store import PairingStore
    PairingStore('/unused/data').folder(ticket)
    return f'''#!/bin/sh
umask 077
base={shlex.quote(base)}
op="$base/{ticket}"
exec 9>/tmp/fit-lab-radio.flock
flock -n 9 || {{ [ -d "$op/launched" ] || echo busy > "$op/status"; exit 75; }}
mkdir "$op/launched" 2>/dev/null || exit 0
[ ! -f "$op/cancel" ] || {{ echo cancelled > "$op/status"; exit 1; }}
[ ! -f "$base/pending" ] || {{ echo busy > "$op/status"; exit 75; }}
restart_radio() {{
{restart}
}}
rollback() {{
  trap '' HUP INT TERM
  echo rolling_back > "$op/status"
  cp "$op/previous.key" {shlex.quote(key + '.fitlab.tmp')} &&
  chmod 600 {shlex.quote(key + '.fitlab.tmp')} &&
  mv {shlex.quote(key + '.fitlab.tmp')} {shlex.quote(key)} || {{ echo rollback_failed > "$op/status"; exit 1; }}
  sync
  restart_radio || {{ echo rollback_failed > "$op/status"; exit 1; }}
  echo rolled_back > "$op/status"
  rm -f "$base/pending"
  sync
  exit 1
}}
[ -f {shlex.quote(key)} ] && [ ! -L {shlex.quote(key)} ] && [ "$(wc -c < {shlex.quote(key)})" -eq 64 ] &&
[ -f "$op/new.key" ] && [ "$(wc -c < "$op/new.key")" -eq 64 ] || {{ echo invalid_key > "$op/status"; exit 1; }}
{preflight}
cp {shlex.quote(key)} "$op/previous.key" && chmod 600 "$op/previous.key" || {{ echo backup_failed > "$op/status"; exit 1; }}
echo {ticket} > "$base/pending"
sync
trap rollback HUP INT TERM
cp "$op/new.key" {shlex.quote(key + '.fitlab.tmp')} &&
chmod 600 {shlex.quote(key + '.fitlab.tmp')} &&
mv {shlex.quote(key + '.fitlab.tmp')} {shlex.quote(key)} || rollback
sync
echo restarting > "$op/status"
restart_radio || rollback
echo verifying > "$op/status"
count=0
while [ "$count" -lt {int(ticks)} ]; do
  [ -f "$op/cancel" ] && rollback
  if [ "$(cat "$op/commit" 2>/dev/null)" = {ticket} ]; then
    echo committed > "$op/status"
    sync
    rm -f "$base/pending"
    sync
    exit 0
  fi
  count=$((count+1))
  sleep 0.1
done
rollback
'''
