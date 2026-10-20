#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo.'
  exit 1
fi
source_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
apt-get update
apt-get install -y python3 python3-venv iproute2
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
