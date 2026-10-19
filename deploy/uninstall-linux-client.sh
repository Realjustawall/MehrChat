#!/usr/bin/env bash
set -euo pipefail
install_root="${XDG_DATA_HOME:-$HOME/.local/share}/MehrChatApp"
python3 - "$install_root" "${XDG_DATA_HOME:-$HOME/.local/share}/applications/mehrchat.desktop" <<'PY'
import shutil, sys
from pathlib import Path
target, shortcut = map(Path, sys.argv[1:])
if target.is_symlink():
    target.unlink()
elif target.exists():
    shutil.rmtree(target)
shortcut.unlink(missing_ok=True)
print('Account data in MehrChat/identity.mcv has been preserved.')
PY
