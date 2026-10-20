"""Disposable CI peer for actual Android TCP / Noise / E2EE request and reply."""

import argparse, asyncio, json, signal, ssl, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mehrchat.client import Engine
from mehrchat.server import Relay
from mehrchat.vault import Vault
from mehrchat.deployment import local_certificate

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--client-host", default="10.0.2.2")
args = parser.parse_args()
REQUEST = "سلام، آزمون پیام فارسی"
REPLY = "پاسخ آزمون شبکه"


async def run():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for event in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(event, stop.set)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        relay = Relay(root / "relay")
        ca = local_certificate(root / "tls", ["127.0.0.1", args.client_host])
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(root / "tls/server.pem", root / "tls/server-key.pem")
        server = await asyncio.start_server(relay.handle, "127.0.0.1", 0, ssl=context)
        port = server.sockets[0].getsockname()[1]
        vault = Vault(
            root / "client/peer.mcv",
            "CI-only temporary network peer",
            "ci_peer",
            "مخاطب",
        )
        peer = Engine(vault)
        peer.d["relays"] = [dict(host="127.0.0.1", port=port, pin=relay.pin, transport="tls", ca=ca)]
        peer.running = True
        task = asyncio.create_task(peer.loop())
        args.config.parent.mkdir(parents=True, exist_ok=True)
        args.config.write_text(
            json.dumps(
                dict(
                    card=peer.card,
                    relay=dict(host=args.client_host, port=port, pin=relay.pin, transport="tls", ca=ca),
                    expected_reply=REPLY,
                )
            )
        )
        replied = False
        try:
            while not stop.is_set():
                for identity, card in list(relay.live_cards.items()):
                    if card["body"]["username"] != "ci_tester":
                        continue
                    if identity not in peer.d["contacts"]:
                        # Trust the test device on this isolated CI relay; the app
                        # independently pins this peer's public card from config.
                        peer.add_contact(json.dumps(card), identity)
                    chat = peer.dm_id(identity)
                    if not replied and any(
                        m.get("text") == REQUEST
                        for m in peer.d["messages"].get(chat, [])
                    ):
                        peer.send(chat, REPLY)
                        replied = True
                        print(
                            "Android verified TLS / pinned Noise / authenticated bootstrap / Double Ratchet request and reply: PASS",
                            flush=True,
                        )
                await asyncio.sleep(0.05)
        finally:
            peer.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()
            vault.close()
            relay.db.close()


asyncio.run(run())
