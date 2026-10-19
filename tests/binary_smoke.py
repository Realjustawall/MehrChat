"""Compiled relay smoke: actual bootstrap, DR, receipt, deletion and queue inspection."""

import asyncio, json, os, socket, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mehrchat.client import Engine
from mehrchat.crypto import create_identity


class MemoryVault:
    def __init__(self, name):
        self.data = dict(
            identity=create_identity(name, name),
            contacts={},
            groups={},
            messages={},
            outbox=[],
            seen={},
            deleted={},
            relays=[],
        )

    def save(self):
        pass


async def run():
    def port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    tcp, admin = port(), port()
    binary = (
        Path(__file__).resolve().parent.parent
        / "dist"
        / ("MehrRelay.exe" if os.name == "nt" else "MehrRelay")
    )
    with tempfile.TemporaryDirectory() as root:
        process = subprocess.Popen(
            [
                str(binary),
                "--host",
                "127.0.0.1",
                "--port",
                str(tcp),
                "--admin-port",
                str(admin),
                "--data",
                root,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        engines = []
        tasks = []

        async def until(predicate):
            for _ in range(400):
                if predicate():
                    return
                await asyncio.sleep(0.05)
            raise AssertionError("Compiled relay timed out")

        try:
            first = await asyncio.wait_for(
                asyncio.to_thread(process.stdout.readline), 20
            )
            if not first.startswith("Server public pin: "):
                raise RuntimeError("Compiled relay did not announce its pin")
            pin = first.split(": ", 1)[1].strip()
            a, b = Engine(MemoryVault("alice")), Engine(MemoryVault("bobby"))
            engines = [a, b]
            a.add_contact(json.dumps(b.card), b.me)
            b.add_contact(json.dumps(a.card), a.me)
            for e in engines:
                e.d["relays"] = [dict(host="127.0.0.1", port=tcp, pin=pin)]
                e.running = True
                tasks.append(asyncio.create_task(e.loop()))
            chat = a.dm_id(b.me)
            mid = a.send(chat, "NATIVE-PRIVATE-CONTENT-سلام")
            await until(lambda: bool(b.d["messages"].get(chat)))
            await until(lambda: a.d["messages"][chat][0]["state"] == "تحویل شد")
            assert b.d["messages"][chat][0]["text"] == "NATIVE-PRIVATE-CONTENT-سلام"
            b.delete(chat, mid)
            await until(lambda: not a.d["messages"][chat])
            for path in Path(root).glob("queue.sqlite*"):
                raw = path.read_bytes()
                assert b"NATIVE-PRIVATE-CONTENT" not in raw
                for e in engines:
                    assert e.identity["box_secret"].encode() not in raw
            print(
                "Compiled relay Noise / bootstrap / Double Ratchet / receipt / bilateral deletion: PASS"
            )
            print("Queue plaintext and user private-key checks: PASS")
        finally:
            for e in engines:
                e.stop()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if process.poll() is None:
                if os.name == "nt":
                    # One-file PyInstaller uses a parent bootloader and a child.
                    # Terminating only the parent leaves SQLite open on Windows.
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                else:
                    process.terminate()
            process.wait(timeout=10)


asyncio.run(run())
