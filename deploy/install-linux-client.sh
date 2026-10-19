#!/usr/bin/env bash
set -euo pipefail
package_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
install_root="${XDG_DATA_HOME:-$HOME/.local/share}/MehrChatApp"
mkdir -p "$install_root" "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
cp -a "$package_root/dist/MehrChat/." "$install_root/"
chmod +x "$install_root/MehrChat"
cat > "${XDG_DATA_HOME:-$HOME/.local/share}/applications/mehrchat.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=MehrChat
Exec="$install_root/MehrChat"
Terminal=false
Categories=Network;InstantMessaging;
DESKTOP
