#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo.'
  exit 1
fi
source_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
source /etc/os-release
if [ "${ID:-}" != ubuntu ] || ! command -v systemctl >/dev/null; then
  echo 'This installer requires Ubuntu with systemd. Use the offline package for other supported systems.'
  exit 1
fi
exec 9>/run/lock/mehrchat-install.lock
flock -n 9 || { echo 'Another MehrChat installation is running.'; exit 1; }
trap 'echo "Setup stopped. Inspect: journalctl -u mehr-relay -n 80 --no-pager" >&2' ERR
umask 022
apt-get update
apt-get install -y python3 python3-venv iproute2 ca-certificates gh
id mehrchat >/dev/null 2>&1 || useradd --system --home /var/lib/mehrchat --shell /usr/sbin/nologin mehrchat
install -d -o mehrchat -g mehrchat -m 700 /var/lib/mehrchat
install -d -m 755 /opt/mehrchat /opt/mehrchat/deploy /opt/mehrchat/scripts
cp -r "$source_root/mehrchat" "$source_root/assets" /opt/mehrchat/
cp "$source_root/requirements-server.txt" /opt/mehrchat/
cp "$source_root/deploy/setup-ubuntu.py" /opt/mehrchat/deploy/
cp "$source_root/scripts/request-client-build.py" /opt/mehrchat/scripts/
python3 -m venv /opt/mehrchat/venv
/opt/mehrchat/venv/bin/python -m pip install -r /opt/mehrchat/requirements-server.txt
install -m 644 "$source_root/deploy/mehr-relay.service" /etc/systemd/system/mehr-relay.service
cd /opt/mehrchat
export PYTHONPATH=/opt/mehrchat
/opt/mehrchat/venv/bin/python deploy/setup-ubuntu.py
