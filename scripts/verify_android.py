"""Inspect the actual APK, including nested Python native libraries and pinned metadata."""

import argparse, email, io, json, struct, subprocess, tarfile, tempfile, zipfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("apk", type=Path)
p.add_argument("--arch", choices=["arm64-v8a", "x86_64"], required=True)
p.add_argument("--release", action="store_true")
p.add_argument("--build-tools", type=Path, required=True)
args = p.parse_args()
expected = 183 if args.arch == "arm64-v8a" else 62
report = {
    "apk": args.apk.name,
    "arch": args.arch,
    "elf_count": 0,
    "versions": {},
    "python_linked_extensions": [],
    "debuggable": not args.release,
}


def elf(name, raw):
    if not raw.startswith(b"\x7fELF"):
        return
    assert raw[4] == 2 and raw[5] == 1, (name, "unsupported ELF")
    assert struct.unpack_from("<H", raw, 18)[0] == expected, (
        name,
        "wrong architecture",
    )
    off = struct.unpack_from("<Q", raw, 32)[0]
    size, num = struct.unpack_from("<HH", raw, 54)
    for i in range(num):
        at = off + i * size
        if struct.unpack_from("<I", raw, at)[0] == 1:
            assert struct.unpack_from("<Q", raw, at + 48)[0] >= 16384, (
                name,
                "ELF not aligned for 16 KiB pages",
            )
    if "cryptography/hazmat/bindings/_rust" in name or "/_pydantic_core." in name:
        with tempfile.NamedTemporaryFile(suffix=".so") as library:
            library.write(raw)
            library.flush()
            dynamic = subprocess.check_output(
                ["readelf", "-d", library.name], text=True
            )
        assert "Shared library: [libpython3.13.so]" in dynamic, (
            name,
            "missing Android Python runtime link",
        )
        report["python_linked_extensions"].append(name)
    report["elf_count"] += 1


with zipfile.ZipFile(args.apk) as z:
    assert {n.split("/")[1] for n in z.namelist() if n.startswith("lib/")} == {
        args.arch
    }
    with tarfile.open(
        fileobj=io.BytesIO(z.read("assets/private.tar")), mode="r:*"
    ) as t:
        names = t.getnames()
        assert any(n in names for n in ("main.py", "main.pyc"))
        assert "assets/Vazirmatn-Regular.ttf" in names
        assert not any(
            Path(n).name in ("identity.mcv", "transport-key.json", "admin-token.txt")
            for n in names
        )
        env = t.extractfile("p4a_env_vars.txt").read().decode()
        assert {line.split("=", 1)[0] for line in env.splitlines()} <= {
            "P4A_IS_WINDOWED",
            "KIVY_ORIENTATION",
            "P4A_NUMERIC_VERSION",
            "P4A_MINSDK",
        }
    for name in z.namelist():
        if not name.endswith(".so"):
            continue
        raw = z.read(name)
        if name.endswith("/libpybundle.so"):
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as t:
                for member in t.getmembers():
                    if not member.isfile():
                        continue
                    if member.name.endswith(".so"):
                        elf(member.name, t.extractfile(member).read())
                    if member.name.endswith(".dist-info/METADATA"):
                        m = email.message_from_bytes(t.extractfile(member).read())
                        key = m["Name"].lower().replace("_", "-")
                        old = report["versions"].get(key)
                        assert old is None or old == m["Version"], (
                            key,
                            "conflicting cached versions",
                        )
                        report["versions"][key] = m["Version"]
        else:
            elf(name, raw)
assert (
    len(report["python_linked_extensions"]) >= 2
), "Rust crypto/model extensions not inspected"
for name, version in {
    "pynacl": "1.6.2",
    "cryptography": "50.0.2",
    "doubleratchet": "1.3.0",
    "noiseprotocol": "0.3.1",
    "chardet": "5.2.0",
}.items():
    assert report["versions"].get(name) == version, (name, report["versions"].get(name))
xml = subprocess.check_output(
    [
        str(args.build_tools / "aapt2"),
        "dump",
        "xmltree",
        str(args.apk),
        "--file",
        "AndroidManifest.xml",
    ],
    text=True,
)
assert "allowBackup" in xml and any(
    "allowBackup" in l and "=false" in l for l in xml.splitlines()
)
assert not args.release or not any(
    "debuggable" in l and "=true" in l for l in xml.splitlines()
)
if not args.release:
    subprocess.run(
        [str(args.build_tools / "apksigner"), "verify", "--verbose", str(args.apk)],
        check=True,
    )
print(json.dumps(report, indent=2))
print(
    "APK payload / architecture / pinned versions / 16 KiB ELF alignment / manifest: PASS"
)
