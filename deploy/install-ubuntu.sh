#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo.'
  exit 1
fi
source_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
apt-get update
apt-get install -y python3 python3-venv
id mehrchat >/dev/null 2>&1 || useradd --system --home /var/lib/mehrchat --shell /usr/sbin/nologin mehrchat
install -d -o mehrchat -g mehrchat -m 700 /var/lib/mehrchat
install -d -m 755 /opt/mehrchat
cp -r "$source_root/mehrchat" /opt/mehrchat/
cp "$source_root/requirements-server.txt" /opt/mehrchat/
python3 -m venv /opt/mehrchat/venv
/opt/mehrchat/venv/bin/python -m pip install -r /opt/mehrchat/requirements-server.txt
install -m 644 "$source_root/deploy/mehr-relay.service" /etc/systemd/system/mehr-relay.service
systemctl daemon-reload
systemctl enable --now mehr-relay
printf '%s\n' 'Open TCP 8787 in your VPS firewall. Admin is loopback-only on 8788.' 'Server pin: sudo journalctl -u mehr-relay' 'Admin token: sudo cat /var/lib/mehrchat/admin-token.txt'
