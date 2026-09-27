"""Password transaction scripts. Passwords are received on SSH stdin only."""
import re
import shlex

BASE = '/etc/fit-lab-security'
BOOT = '/etc/init.d/S01fitlab-security'


def guardian(base=BASE, shadow='/etc/shadow', chpasswd='/usr/sbin/chpasswd'):
    return f'''#!/bin/sh
# FIT-LAB password rollback v1
umask 077
base={shlex.quote(base)}
shadow={shlex.quote(shadow)}
[ -f "$base/pending" ] || exit 0
ticket=$(cat "$base/pending")
case "$ticket" in *[!0-9a-f]*|'') exit 1;; esac
[ "${{#ticket}}" = 32 ] || exit 1
[ -z "$3" ] || [ "$3" = "$ticket" ] || exit 1
op="$base/$ticket"
if [ "$1" = watch ]; then
  sleep "${{2:-150}}"
fi
exec 9>"$base/lock"
n=0
until flock -n 9; do
  n=$((n + 1)); [ "$n" -lt 10 ] || exit 1
  sleep 1
done
[ "$(cat "$base/pending" 2>/dev/null)" = "$ticket" ] || exit 0
[ "$(cat "$op/state" 2>/dev/null)" != committed ] || exit 0
[ -s "$op/previous.hash" ] || exit 1
current=$(awk -F: '$1=="root" {{print $2}}' "$shadow")
previous=$(cat "$op/previous.hash")
if [ -s "$op/new.hash" ] && [ "$current" != "$(cat "$op/new.hash")" ] && [ "$current" != "$previous" ]; then
  echo conflict > "$op/state"
  exit 1
fi
printf 'root:%s\\n' "$previous" | {shlex.quote(chpasswd)} -e >/dev/null 2>&1 || exit 1
sync
echo rolled_back > "$op/state"
rm -f "$base/pending" "$op/previous.hash" "$op/new.hash"
sync
'''


def boot_script():
    return f'''#!/bin/sh
# FIT-LAB password rollback v1
[ "$1" = start ] || exit 0
exec /bin/sh {BASE}/guardian.sh boot
'''


def apply_script(ticket, base=BASE, shadow='/etc/shadow', chpasswd='/usr/sbin/chpasswd', wait=150):
    if not re.fullmatch('[0-9a-f]{32}', ticket):
        raise ValueError('Invalid transaction')
    return f'''umask 077
base={shlex.quote(base)}
op="$base/{ticket}"
exec 9>"$base/lock"
flock -n 9 || exit 75
[ ! -e "$base/pending" ] || exit 75
IFS= read -r password || exit 1
[ "${{#password}}" -ge 24 ] && [ "${{#password}}" -le 64 ] || exit 1
case "$password" in *[!A-Za-z0-9_-]*) exit 1;; esac
mkdir "$op" || exit 1
awk -F: '$1=="root" {{print $2}}' {shlex.quote(shadow)} > "$op/previous.hash"
[ -s "$op/previous.hash" ] || exit 1
echo preparing > "$op/state"
echo {ticket} > "$base/pending"
sync
nohup /bin/sh "$base/guardian.sh" watch {int(wait)} {ticket} </dev/null >/dev/null 2>&1 9>&- &
watchdog=$!
kill -0 "$watchdog" || exit 1
printf 'root:%s\\n' "$password" | {shlex.quote(chpasswd)} -c sha512 >/dev/null 2>&1 || exit 1
unset password
awk -F: '$1=="root" {{print $2}}' {shlex.quote(shadow)} > "$op/new.hash"
sync
echo applied > "$op/state"
sync
echo applied
'''


def commit_script(ticket, base=BASE, shadow='/etc/shadow'):
    if not re.fullmatch('[0-9a-f]{32}', ticket):
        raise ValueError('Invalid transaction')
    return f'''base={shlex.quote(base)}
op="$base/{ticket}"
exec 9>"$base/lock"
n=0
until flock -n 9; do
  n=$((n + 1)); [ "$n" -lt 5 ] || exit 75
  sleep 1
done
[ "$(cat "$op/state" 2>/dev/null)" = committed ] && {{ echo committed; exit 0; }}
[ "$(cat "$base/pending" 2>/dev/null)" = {ticket} ] || exit 1
[ "$(cat "$op/state")" = applied ] || exit 1
[ "$(awk -F: '$1=="root" {{print $2}}' {shlex.quote(shadow)})" = "$(cat "$op/new.hash")" ] || exit 1
echo committed > "$op/state"
sync
rm -f "$base/pending" "$op/previous.hash" "$op/new.hash"
sync
echo committed
'''
