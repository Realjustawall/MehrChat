"""Verify the real installed service's Noise listener without logging its keys."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import argparse, asyncio, json
from pathlib import Path
from mehrchat.crypto import create_identity, public_card
from mehrchat.wire import connect

p = argparse.ArgumentParser()
p.add_argument("data", type=Path)
args = p.parse_args()


async def run():
    public = None
    for _ in range(100):
        try:
            public = json.loads((args.data / "relay-public.json").read_text())
            break
        except (OSError, ValueError):
            await asyncio.sleep(0.2)
    assert public, "Installed service did not publish its connection pin"
    identity = create_identity("ci_install", "CI install test")
    ch = None
    for _ in range(100):
        try:
            ch = await connect(
                "127.0.0.1",
                public["port"],
                public["pin"],
                identity,
                public_card(identity),
            )
            break
        except (OSError, ConnectionError):
            await asyncio.sleep(0.2)
    assert ch, "Installed service listener unavailable"
    try:
        await ch.send({"op": "settings"})
        response = await ch.recv()
        assert response["ok"] and response["files_enabled"] is False
        print("Installed relay startup / pinned Noise / authenticated request: PASS")
    finally:
        await ch.close()


asyncio.run(run())
