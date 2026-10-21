"""Run on the target OS. PyInstaller does not cross-compile Windows from Linux."""

import os
import shutil
from pathlib import Path
import sys
import PyInstaller.__main__

root = Path(__file__).resolve().parent.parent
os.chdir(root)
kind = sys.argv[1] if len(sys.argv) > 1 else "client"
if kind == "client" and (root / "dist" / "MehrChat").exists():
    shutil.rmtree(root / "dist" / "MehrChat")
args = [
    "--noconfirm",
    "--clean",
    "--hidden-import",
    "_cffi_backend",
    "--exclude-module",
    "lxml",
    "--exclude-module",
    "matplotlib",
    "--exclude-module",
    "tkinter",
    "--exclude-module",
    "IPython",
    "--exclude-module",
    "pandas",
    "--exclude-module",
    "Cython",
    "--exclude-module",
    "pyximport",
]
if kind == "client" and sys.platform == "win32":
    from kivy_deps import angle, glew, sdl2

    libraries = {}
    for dependency in (angle, glew, sdl2):
        for directory in dependency.dep_bins:
            for library in Path(directory).glob("*.dll"):
                libraries.setdefault(library.name.lower(), library)
    if not {"libegl.dll", "libglesv2.dll"} <= set(libraries):
        raise RuntimeError("ANGLE runtime DLLs were not installed")
    for library in libraries.values():
        args += ["--add-binary", str(library) + os.pathsep + "."]
    print("Bundled Windows graphics libraries:", len(libraries), flush=True)

if sys.platform.startswith("linux"):
    args += ["--strip"]
if kind == "server":
    args += [
        "--onefile",
        "--name",
        "MehrRelay",
        "--add-data",
        "assets" + os.pathsep + "assets",
        "relay.py",
    ]
else:
    args += [
        "--onedir",
        "--windowed",
        "--name",
        "MehrChat",
        "--add-data",
        "assets" + os.pathsep + "assets",
        "main.py",
    ]
if kind == 'client':
    args += ['--collect-all', 'zxingcpp', '--collect-all', 'cv2', '--collect-all', 'qrcode']
PyInstaller.__main__.run(args)
