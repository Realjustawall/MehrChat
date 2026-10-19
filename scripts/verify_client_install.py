"""CI-only real desktop install/uninstall and encrypted identity retention test."""

import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mehrchat.vault import Vault
from mehrchat.crypto import public_card

assert os.environ.get("GITHUB_ACTIONS") == "true", "Run only on a disposable CI runner"
base = Path(os.environ.get("APPDATA", str(Path.home() / ".local/share")))
identity_path = base / "MehrChat/identity.mcv"
assert not identity_path.exists(), "Refusing to replace an existing account"
password = "CI-only installer test password"
vault = Vault(identity_path, password, "install_test", "آزمون نصب")
fingerprint = public_card(vault.data["identity"])["body"]["id"]
vault.close()
original = identity_path.read_bytes()

try:
    if os.name == "nt":
        install = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "deploy/install-windows-client.ps1"),
            "-NoLaunch",
        ]
        uninstall = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "deploy/uninstall-windows-client.ps1"),
        ]
        executable = Path(os.environ["LOCALAPPDATA"]) / "Programs/MehrChat/MehrChat.exe"
    else:
        install = ["bash", str(ROOT / "deploy/install-linux-client.sh")]
        uninstall = ["bash", str(ROOT / "deploy/uninstall-linux-client.sh")]
        executable = (
            Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
            / "MehrChatApp/MehrChat"
        )
    subprocess.run(install, check=True)
    assert executable.is_file()
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/native_gui_smoke.py"),
            "--exe",
            str(executable),
        ],
        check=True,
    )
    subprocess.run(uninstall, check=True)
    assert not executable.exists()
    assert identity_path.read_bytes() == original
    restored = Vault(identity_path, password)
    assert public_card(restored.data["identity"])["body"]["id"] == fingerprint
    restored.close()
    print(
        "Desktop install / installed GUI and crypto / uninstall / encrypted identity retention: PASS"
    )
finally:
    identity_path.unlink(missing_ok=True)
    identity_path.with_suffix(".lock").unlink(missing_ok=True)
