"""Package whole runtimes; Linux tar preserves required shared-library symlinks."""

import hashlib, json, os, shutil, tarfile, zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
out = root / "packages"
out.mkdir(exist_ok=True)
name = "MehrChat-Windows-x64" if os.name == "nt" else "MehrChat-Ubuntu-x64"
files = [
    root / "dist/MehrChat",
    root / "dist" / ("MehrRelay.exe" if os.name == "nt" else "MehrRelay"),
    root / "deploy",
    root / "reports",
]
files += [
    root / p for p in ("README.md", "README.fa.md", "SECURITY.md", "BUILD_STATUS.md")
]
if os.name == "nt":
    archive = out / (name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            if p.is_file():
                z.write(p, name + "/" + str(p.relative_to(root)))
            else:
                for f in p.rglob("*"):
                    if f.is_file():
                        z.write(f, name + "/" + str(f.relative_to(root)))
else:
    archive = out / (name + ".tar.gz")
    with tarfile.open(archive, "w:gz") as t:
        for p in files:
            t.add(p, arcname=name + "/" + str(p.relative_to(root)))
(out / (archive.name + ".sha256")).write_text(
    hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n"
)
print("Packaged", archive.name)
