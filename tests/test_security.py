import asyncio
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from nacl.exceptions import CryptoError, BadSignatureError
from nacl.public import PrivateKey, SealedBox
from mehrchat.crypto import *
from mehrchat.vault import Vault
from mehrchat.client import Engine
from mehrchat.server import Relay
from mehrchat.wire import connect, write_frame, read_frame, MAX_FRAME


class MemoryVault:
    def __init__(self, name):
        self.data = {
            "identity": create_identity(name, name),
            "contacts": {},
            "groups": {},
            "messages": {},
            "outbox": [],
            "seen": [],
            "deleted": {},
            "relays": [],
        }

    def save(self):
        pass


def pump(engines):
    for _ in range(40):
        changed = False
        by_id = {e.me: e for e in engines}
        for source in engines:
            outgoing = list(source.d["outbox"])
            source.d["outbox"] = []
            for entry in outgoing:
                try:
                    by_id[entry["item"]["body"]["to"]].ingest(entry["item"])
                except KeyError:
                    by_id[entry["item"]["body"]["to"]].d["quarantine"].append(
                        entry["item"]
                    )
                changed = True
        for e in engines:
            e.retry_quarantine()
        if not changed:
            return
    raise AssertionError("Protocol did not settle")


def clients():
    engines = [Engine(MemoryVault(n)) for n in ("alice", "bobby", "carol")]
    for e in engines:
        for other in engines:
            if other is not e:
                e.add_contact(json.dumps(other.card), other.me)
    for e in engines:
        for other in engines:
            if e.me < other.me:
                e.secure.ensure(other.me)
    pump(engines)
    return engines


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c = clients()

    def test_only_recipient_decrypts(self):
        item = envelope(
            self.a.identity, self.b.card, {"text": "secret"}, int(time.time()) + 100
        )
        self.assertEqual(
            open_envelope(self.b.identity, self.a.card, item)["text"], "secret"
        )
        with self.assertRaises(ValueError):
            open_envelope(self.c.identity, self.a.card, item)
        with self.assertRaises(CryptoError):
            SealedBox(PrivateKey.generate()).decrypt(dec(item["body"]["ciphertext"]))

    def test_ciphertext_tamper(self):
        item = envelope(self.a.identity, self.b.card, {}, int(time.time()) + 100)
        tampered = bytearray(dec(item["body"]["ciphertext"]))
        tampered[0] ^= 1
        item["body"]["ciphertext"] = enc(tampered)
        with self.assertRaises((BadSignatureError, CryptoError)):
            open_envelope(self.b.identity, self.a.card, item)

    def test_route_tamper(self):
        item = envelope(self.a.identity, self.b.card, {}, int(time.time()) + 100)
        item["body"]["expires"] += 10
        with self.assertRaises(BadSignatureError):
            open_envelope(self.b.identity, self.a.card, item)

    def test_forged_card(self):
        card = copy.deepcopy(self.a.card)
        card["body"]["box"] = self.c.card["body"]["box"]
        with self.assertRaises(ValueError):
            check_card(card)

    def test_fingerprint_required(self):
        with self.assertRaises(ValueError):
            self.a.add_contact(json.dumps(self.b.card), "0" * 64)

    def test_expiry(self):
        item = envelope(self.a.identity, self.b.card, {}, int(time.time()) - 1)
        with self.assertRaises(ValueError):
            open_envelope(self.b.identity, self.a.card, item)

    def test_replay_ignored(self):
        chat = self.a.dm_id(self.b.me)
        self.a.send(chat, "one")
        item = self.a.d["outbox"][0]["item"]
        self.b.ingest(item)
        self.b.ingest(item)
        self.assertEqual(len(self.b.d["messages"][chat]), 1)

    def test_recipient_can_delete_both_sides(self):
        chat = self.a.dm_id(self.b.me)
        mid = self.a.send(chat, "hello")
        self.b.ingest(self.a.d["outbox"][0]["item"])
        self.b.delete(chat, mid)
        self.a.ingest(
            next(
                p["item"]
                for p in self.b.d["outbox"]
                if p["item"]["body"]["kind"] == "delete"
            )
        )
        self.assertEqual(self.a.d["messages"][chat], [])
        self.assertEqual(self.b.d["messages"][chat], [])

    def test_delete_before_original_does_not_resurrect(self):
        chat = self.a.dm_id(self.b.me)
        mid = self.a.send(chat, "hello")
        original = self.a.d["outbox"][0]["item"]
        self.a.delete(chat, mid)
        deletion = self.a.d["outbox"][0]["item"]
        self.b.ingest(deletion)
        self.b.ingest(original)
        self.assertFalse(self.b.d["messages"][chat])

    def test_group_fanout(self):
        group = self.a.create_group("دوستان", [self.b.me, self.c.me])
        for entry in self.a.d["outbox"]:
            engine = self.b if entry["item"]["body"]["to"] == self.b.me else self.c
            engine.ingest(entry["item"])
        self.assertIn(group, self.b.d["groups"])
        self.assertIn(group, self.c.d["groups"])
        self.b.d["outbox"] = []
        self.b.send(group, "group secret")
        for entry in self.b.d["outbox"]:
            engine = self.a if entry["item"]["body"]["to"] == self.a.me else self.c
            engine.ingest(entry["item"])
        self.assertEqual(self.c.d["messages"][group][-1]["text"], "group secret")

    def test_group_cannot_delete_other_member(self):
        group = self.a.create_group("دوستان", [self.b.me, self.c.me])
        item = next(
            x["item"]
            for x in self.a.d["outbox"]
            if x["item"]["body"]["to"] == self.b.me
        )
        self.b.ingest(item)
        with self.assertRaises(ValueError):
            self.b.delete(group, self.b.d["messages"][group][0]["id"])

    def test_group_unknown_member_not_trusted(self):
        group = self.a.create_group("دوستان", [self.b.me, self.c.me])
        self.b.d["contacts"].pop(self.c.me)
        item = next(
            x["item"]
            for x in self.a.d["outbox"]
            if x["item"]["body"]["to"] == self.b.me
        )
        self.b.ingest(item)
        self.assertNotIn(self.c.me, self.b.d["contacts"])
        with self.assertRaises(KeyError):
            self.b.validate_chat({"private": [self.b.me, self.c.me]}, self.c.me)

    def test_expiry_prunes_local_and_outbox(self):
        chat = self.a.dm_id(self.b.me)
        self.a.send(chat, "bye", ttl=3600)
        with patch("mehrchat.client.time.time", return_value=time.time() + 3601):
            self.a.prune()
        self.assertFalse(self.a.d["messages"][chat])
        self.assertFalse(self.a.d["outbox"])

    def test_file_disabled(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "file.bin"
            path.write_bytes(b"secret file")
            with self.assertRaises(ValueError):
                self.a.send(self.a.dm_id(self.b.me), file_path=path)

    def test_file_roundtrip_and_no_path_traversal(self):
        self.a.files_enabled = True
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "document.txt"
            source.write_bytes(b"private bytes")
            chat = self.a.dm_id(self.b.me)
            mid = self.a.send(chat, file_path=source)
            self.b.ingest(self.a.d["outbox"][0]["item"])
            target = Path(root) / "chosen.txt"
            self.b.export_file(chat, mid, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            with self.assertRaises(FileExistsError):
                self.b.export_file(chat, mid, target)


class VaultTests(unittest.TestCase):
    def test_password_encryption_backup_restore_and_tamper(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "identity.mcv"
            vault = Vault(path, "correct horse battery staple", "alice", "علی")
            vault.data["sensitive"] = "plaintext must never exist on disk"
            vault.save()
            self.assertNotIn(b"plaintext must never", path.read_bytes())
            self.assertNotIn(b"sign_secret", path.read_bytes())
            with self.assertRaises(CryptoError):
                Vault(path, "a wrong long password")
            loaded = Vault(path, "correct horse battery staple")
            self.assertEqual(loaded.data["identity"], vault.data["identity"])
            backup = Path(root) / "backup.mcv"
            vault.backup(backup)
            path.unlink()
            restored = Vault.restore(backup, path, "correct horse battery staple")
            self.assertEqual(
                public_card(restored.data["identity"]),
                public_card(vault.data["identity"]),
            )
            restored.close()
            raw = bytearray(path.read_bytes())
            raw[-1] ^= 1
            path.write_bytes(raw)
            with self.assertRaises(CryptoError):
                Vault(path, "correct horse battery staple")

    def test_short_password_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                Vault(Path(root) / "v", "short", "alice", "Alice")


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.relay = Relay(self.tmp.name)
        self.server = await asyncio.start_server(self.relay.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.a, self.b, self.c = clients()
        self.channels = []

    async def asyncTearDown(self):
        for channel in self.channels:
            await channel.close()
        self.server.close()
        await self.server.wait_closed()
        await asyncio.sleep(0.05)
        self.relay.db.close()
        self.tmp.cleanup()

    async def channel(self, engine, pin=None):
        ch = await connect(
            "127.0.0.1", self.port, pin or self.relay.pin, engine.identity, engine.card
        )
        self.channels.append(ch)
        return ch

    async def request(self, ch, payload):
        await ch.send(payload)
        return await ch.recv()

    async def test_network_offline_delivery_ack_isolation(self):
        ca = await self.channel(self.a)
        chat = self.a.dm_id(self.b.me)
        self.a.send(chat, "INTEGRATION-SECRET-FA-سلام")
        entry = self.a.d["outbox"][0]["item"]
        self.assertTrue((await self.request(ca, {"op": "put", "item": entry}))["ok"])
        self.assertTrue((await self.request(ca, {"op": "put", "item": entry}))["ok"])
        self.assertEqual(
            self.relay.db.execute("SELECT count(*) FROM queue").fetchone()[0], 1
        )
        self.assertNotIn(
            b"INTEGRATION-SECRET",
            self.relay.db.execute("SELECT data FROM queue").fetchone()[0],
        )
        cc = await self.channel(self.c)
        self.assertIsNone((await self.request(cc, {"op": "fetch"}))["item"])
        await self.request(cc, {"op": "ack", "id": entry["body"]["id"]})
        self.assertEqual(
            self.relay.db.execute("SELECT count(*) FROM queue").fetchone()[0], 1
        )
        cb = await self.channel(self.b)
        got = (await self.request(cb, {"op": "fetch"}))["item"]
        self.b.ingest(got)
        self.assertEqual(
            self.b.d["messages"][chat][-1]["text"], "INTEGRATION-SECRET-FA-سلام"
        )
        await self.request(cb, {"op": "ack", "id": got["body"]["id"]})
        self.assertEqual(
            self.relay.db.execute("SELECT count(*) FROM queue").fetchone()[0], 0
        )

    async def test_wrong_server_pin_fails_closed(self):
        with self.assertRaises(asyncio.IncompleteReadError):
            await self.channel(self.a, self.c.card["body"]["sign"])

    async def test_oversized_frame_rejected(self):
        import struct

        r, w = await asyncio.open_connection("127.0.0.1", self.port)
        w.write(struct.pack("!I", MAX_FRAME + 1))
        await w.drain()
        self.assertEqual(await asyncio.wait_for(r.read(1), 2), b"")
        w.close()
        await w.wait_closed()

    async def test_server_refuses_impersonation(self):
        item = envelope(self.b.identity, self.c.card, {}, int(time.time()) + 100)
        with self.assertRaises((ValueError, BadSignatureError)):
            self.relay.put(self.a.card, item)

    async def test_server_file_toggle_and_expiration(self):
        self.a.files_enabled = True
        self.a.send(self.a.dm_id(self.b.me), file_bytes=b"file", ttl=3600)
        item = self.a.d["outbox"][-1]["item"]
        self.assertFalse(self.relay.put(self.a.card, item)["ok"])
        conf = self.relay.settings()
        conf["files_enabled"] = True
        self.relay.config_path.write_text(json.dumps(conf))
        self.assertTrue(self.relay.put(self.a.card, item)["ok"])
        with patch("mehrchat.server.time.time", return_value=time.time() + 3601):
            self.relay.cleanup()
        self.assertEqual(
            self.relay.db.execute("SELECT count(*) FROM queue").fetchone()[0], 0
        )

    async def test_transport_replay_rejected(self):
        ca = await self.channel(self.a)
        import struct

        raw = pack({"op": "settings"})
        length = ca.noise.encrypt(struct.pack("!I", len(raw)))
        packet = ca.noise.encrypt(raw)
        await write_frame(ca.writer, length)
        await write_frame(ca.writer, packet)
        self.assertTrue((await ca.recv())["ok"])
        await write_frame(ca.writer, length)
        await write_frame(ca.writer, packet)
        with self.assertRaises(asyncio.IncompleteReadError):
            await ca.recv()

    async def test_admin_panel_token(self):
        admin = self.relay.start_admin(0)
        port = admin.server_address[1]
        try:
            req = Request(
                "http://127.0.0.1:%d/" % port,
                data=("token=" + self.relay.admin_token + "&files=yes").encode(),
            )
            with urlopen(req, timeout=3) as response:
                self.assertEqual(response.status, 200)
            self.assertTrue(self.relay.settings()["files_enabled"])
            from urllib.error import HTTPError

            with self.assertRaises(HTTPError):
                urlopen(
                    Request("http://127.0.0.1:%d/" % port, data=b"token=bad"), timeout=3
                )
        finally:
            admin.shutdown()
            admin.server_close()

    async def test_full_engine_sync_delete(self):
        for engine in (self.a, self.b):
            engine.d["relays"] = [
                {"host": "127.0.0.1", "port": self.port, "pin": self.relay.pin}
            ]
            engine.running = True
        chat = self.a.dm_id(self.b.me)
        mid = self.a.send(chat, "full engine sync")
        tasks = [asyncio.create_task(e.loop()) for e in (self.a, self.b)]

        async def until(predicate):
            for _ in range(100):
                if predicate():
                    return
                await asyncio.sleep(0.1)
            self.fail("Sync timeout")

        try:
            await until(lambda: bool(self.b.d["messages"].get(chat)))
            self.b.delete(chat, mid)
            await until(lambda: not self.a.d["messages"][chat])
        finally:
            self.a.stop()
            self.b.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
