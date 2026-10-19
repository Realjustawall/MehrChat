"""Exercise the actual compiled GUI and temporary encrypted account on the target OS."""

import argparse, json, os, subprocess, tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
exe = root / "dist/MehrChat" / ("MehrChat.exe" if os.name == "nt" else "MehrChat")
parser = argparse.ArgumentParser()
parser.add_argument("--exe", type=Path, default=exe)
exe = parser.parse_args().exe
with tempfile.TemporaryDirectory() as directory:
    result = Path(directory) / "result.json"
    env = os.environ.copy()
    env["MEHRCHAT_SMOKE_TEST"] = "flow"
    env["MEHRCHAT_SMOKE_RESULT"] = str(result)
    logfile = Path(directory) / "gui.log"
    env["MEHRCHAT_SMOKE_LOG"] = str(logfile)
    if os.name == "nt":
        env["KIVY_GL_BACKEND"] = "angle_sdl2"
    try:
        run = subprocess.run(
            [str(exe)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        print(run.stdout)
    finally:
        if logfile.exists():
            print(logfile.read_text(encoding="utf-8", errors="replace"))
    if run.returncode:
        raise SystemExit(run.returncode)
    assert result.exists(), "Native GUI did not finish its account/lock/chat flow"
    checks = json.loads(result.read_text())
    assert checks and all(checks.values())
    print(json.dumps(checks, indent=2))
    print("Compiled native GUI account/chat/group/dialog/lock/restore flow: PASS")
