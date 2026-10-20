#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run with sudo.'; exit 1; }
. /etc/os-release
[ "$ID" = ubuntu ] || { echo 'This installer targets Ubuntu.'; exit 1; }
root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
"$root/dist/MehrRelay" --help >/dev/null
id mehrchat >/dev/null 2>&1 || useradd --system --home /var/lib/mehrchat --shell /usr/sbin/nologin mehrchat
install -d -o mehrchat -g mehrchat -m 700 /var/lib/mehrchat
"$root/dist/MehrRelay" --data /var/lib/mehrchat --setup
chown -R mehrchat:mehrchat /var/lib/mehrchat
bash "$root/deploy/install-ubuntu-offline.sh"
echo 'Admin: http://127.0.0.1:8788 (use an SSH tunnel for remote administration).'
echo 'Allow the chosen TLS port in your host/provider firewall.'
read -r -p 'Build dedicated Windows/Android clients through GitHub Actions now? [y/N]: ' build
if [[ "$build" =~ ^[Yy]([Ee][Ss])?$ ]]; then
  command -v gh >/dev/null || { apt-get update; apt-get install -y gh; }
  apt-get update
  apt-get install -y apksigner default-jre-headless
  gh auth status >/dev/null 2>&1 || gh auth login --hostname github.com --git-protocol https --web
  read -r -p 'Repository [Realjustawall/MehrChat]: ' repo
  repo="${repo:-Realjustawall/MehrChat}"
  read -r -p 'Build branch or release tag [fix/security-bilingual-hardening]: ' ref
  ref="${ref:-fix/security-bilingual-hardening}"
  python3 "$root/scripts/build-personalized.py" --profile /var/lib/mehrchat/client-profile.json --repo "$repo" --ref "$ref" --wait --sign --output "$root/dedicated-clients"
fi
