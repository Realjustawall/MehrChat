#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run with sudo.';exit 1; }
package_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
"$package_root/dist/MehrRelay" --help >/dev/null
id mehrchat >/dev/null 2>&1 || useradd --system --home /var/lib/mehrchat --shell /usr/sbin/nologin mehrchat
install -d -o mehrchat -g mehrchat -m 700 /var/lib/mehrchat
install -d -m 755 /opt/mehrchat
install -m 755 "$package_root/dist/MehrRelay" /opt/mehrchat/MehrRelay
cat > /etc/systemd/system/mehr-relay.service <<'UNIT'
[Unit]
Description=MehrChat encrypted relay
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=mehrchat
Group=mehrchat
ExecStart=/opt/mehrchat/MehrRelay --data /var/lib/mehrchat --port 8787
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/mehrchat
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable mehr-relay
systemctl restart mehr-relay
echo 'Open TCP 8787. Pin: /var/lib/mehrchat/relay-public.json'
echo 'Admin panel on server: http://127.0.0.1:8788'
