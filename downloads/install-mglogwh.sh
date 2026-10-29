#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# habang222.pro combined installer. Build sources are pinned to reviewed commits.
readonly SENSOR_REV=5cb573ac5402ca7580fb4c8e0a3f30576a5d38d2
readonly ROOM_REV=5f67113e7f9eea9c12d3105f42ae137723ab2c3e
readonly BOOTSTRAP_REV=d5f36b8ff051c78035696da31e673602c266d93c
collector_started_here=false
work_dir=

fail() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }
on_exit() {
  local status=$?
  trap - EXIT
  if (( status == 0 )); then return; fi
  if [[ $collector_started_here == true ]]; then
    sudo systemctl stop mglogwh.service || true
    echo 'Stopped the collector started by this installer.' >&2
  fi
  echo '[ERROR] Installation did not finish. Review the error above.' >&2
  echo 'Check: sudo systemctl status mglogwh mglogwh-controlroom --no-pager' >&2
  if [[ -n $work_dir ]]; then printf 'Build sources: %s\n' "$work_dir" >&2; fi
  exit "$status"
}
trap on_exit EXIT

(( EUID != 0 )) || fail 'Use an ordinary Ubuntu user, not root. The installer requests sudo when needed.'
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || fail 'Ubuntu 24.04 x86_64 is required.'
[[ -f /etc/os-release ]] || fail 'Cannot identify this Linux distribution.'
# shellcheck disable=SC1091
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || fail 'This installer supports Ubuntu 24.04 only.'
[[ -d /run/systemd/system ]] || fail 'Enable systemd first. In WSL add [boot] and systemd=true to /etc/wsl.conf, then run wsl --shutdown in Windows and reopen Ubuntu.'
[[ -r /sys/kernel/btf/vmlinux ]] || fail 'Kernel BTF is unavailable. WSL users: update WSL and use WSL2.'
command -v sudo >/dev/null || fail 'sudo must be installed for this ordinary user.'

echo 'MGlogWH + Control Room setup for Ubuntu 24.04'
echo 'Installs Linux event collection and a token-protected dashboard at 127.0.0.1:8765.'
echo 'Collection starts after installation. Logs remain in /var/lib/mglogwh.'
echo 'Existing collector code, configuration and run data are kept.'
sudo -v
sudo apt-get update
sudo apt-get install -y ca-certificates curl git build-essential clang libelf-dev zlib1g-dev pkg-config python3 logrotate util-linux
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required"'

if ! mountpoint -q /sys/kernel/tracing; then
  sudo mount -t tracefs tracefs /sys/kernel/tracing
fi
work_dir=$(mktemp -d /tmp/mglogwh-setup.XXXXXXXX)
fetch_source() {
  local name=$1 url=$2 revision=$3
  git init -q "$work_dir/$name"
  git -C "$work_dir/$name" remote add origin "$url"
  git -C "$work_dir/$name" fetch --depth=1 origin "$revision"
  git -C "$work_dir/$name" checkout --detach -q FETCH_HEAD
  [[ $(git -C "$work_dir/$name" rev-parse HEAD) == "$revision" ]] || fail "Revision mismatch: $name"
}

if sudo test -f /opt/mglogwh/manage.py; then
  echo 'Using the existing MGlogWH collector; it will not be replaced.'
else
  fetch_source MGlogWH https://github.com/habang2222/MGlogWH.git "$SENSOR_REV"
  fetch_source libbpf-bootstrap https://github.com/libbpf/libbpf-bootstrap.git "$BOOTSTRAP_REV"
  git -C "$work_dir/libbpf-bootstrap" submodule update --init --recursive
  make -C "$work_dir/libbpf-bootstrap/examples/c" bootstrap
  make -C "$work_dir/MGlogWH"
  sudo bash "$work_dir/MGlogWH/install-ubuntu.sh"
fi

sudo /usr/bin/python3 /opt/mglogwh/manage.py validate --config /etc/mglogwh/config.json
sudo /usr/bin/python3 /opt/mglogwh/manage.py capability
if ! sudo systemctl is-active --quiet mglogwh.service; then
  # Mark before start so a partially started service is stopped on failure.
  collector_started_here=true
  sudo systemctl start mglogwh.service
fi
sensor_ready=false
for attempt in {1..20}; do
  if sudo /usr/bin/python3 /opt/mglogwh/manage.py status | /usr/bin/python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("state") == "RUNNING" else 1)'; then
    sensor_ready=true
    break
  fi
  sleep 1
done
if [[ $sensor_ready != true ]]; then
  echo 'The collector did not reach RUNNING. Inspect sudo journalctl -u mglogwh -n 100 --no-pager' >&2
  false
fi

fetch_source MGlogWH-ControlRoom https://github.com/habang2222/MGlogWH-ControlRoom.git "$ROOM_REV"
if grep -qi microsoft /proc/sys/kernel/osrelease; then
  sudo bash "$work_dir/MGlogWH-ControlRoom/scripts/install-wsl.sh"
else
  sudo bash "$work_dir/MGlogWH-ControlRoom/scripts/install-linux.sh"
fi
sudo systemctl is-active --quiet mglogwh.service
sudo systemctl is-active --quiet mglogwh-controlroom.service
curl --fail --silent --show-error --retry 5 --retry-connrefused --retry-delay 1 --max-time 10 http://127.0.0.1:8765/ -o /dev/null
sudo systemctl enable mglogwh.service
echo
echo '[OK] Collector is RUNNING and Control Room is responding.'
echo 'Open: http://127.0.0.1:8765'
echo 'Read your login token: sudo cat /etc/mglogwh-controlroom/token'
echo 'Stop collection: sudo systemctl stop mglogwh'
echo 'Disable collection on boot: sudo systemctl disable mglogwh'
printf 'Build sources were kept at: %s\n' "$work_dir"
