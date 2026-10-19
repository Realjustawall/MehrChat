"""Start the actual compiled GUI on the target OS; fail on crash or timeout."""

import os, subprocess, time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
exe = root / "dist/MehrChat" / ("MehrChat.exe" if os.name == "nt" else "MehrChat")
env = os.environ.copy()
env["MEHRCHAT_SMOKE_TEST"] = "1"
if os.name == "nt":
    env["KIVY_GL_BACKEND"] = "angle_sdl2"
r = subprocess.run(
    [str(exe)],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    timeout=45,
    text=True,
)
print(r.stdout)
if r.returncode:
    raise SystemExit(r.returncode)
if os.name != "nt" and "NATIVE_UI_SMOKE_OK" not in r.stdout:
    raise RuntimeError("GUI smoke marker missing")
print("Compiled native GUI startup/exit: PASS")
