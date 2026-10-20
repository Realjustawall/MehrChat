import asyncio, copy, json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from test_security import clients, pump, MemoryVault
import test_security as legacy
from mehrchat.client import Engine
from mehrchat.crypto import pack, signed, envelope, public_card, dec, enc
from mehrchat.server import Relay
from mehrchat.vault import Vault


class RatchetTests(unittest.TestCase):
    def setUp(self):
        self.engines = clients()
        self.a, self.b, self.c = self.engines
        self.chat = self.a.dm_id(self.b.me)

    def test_out_of_order(self):
        for text in ("one", "two", "three"):
            self.a.send(self.chat, text)
        for entry in reversed(self.a.d["outbox"]):
            self.b.ingest(entry["item"])
        self.assertEqual(
            {m["text"] for m in self.b.d["messages"][self.chat]},
            {"one", "two", "three"},
        )

    def test_replay_without_application_dedup_is_rejected(self):
        self.a.send(self.chat, "old")
        item = self.a.d["outbox"][-1]["item"]
        self.b.ingest(item)
        state = copy.deepcopy(self.b.d["sessions"][self.a.me])
        self.b.d["seen"] = {}
        with self.assertRaises(Exception):
            self.b.ingest(item)
        self.assertEqual(state, self.b.d["sessions"][self.a.me])

    def test_ratchet_advances_and_bootstrap_secret_is_discarded(self):
        before = copy.deepcopy(self.a.d["sessions"][self.b.me])
        self.a.send(self.chat, "future")
        self.assertNotEqual(before, self.a.d["sessions"][self.b.me])
        self.assertFalse(self.a.d["bootstrap"])
        self.assertNotIn("shared", self.a.d["sessions"][self.b.me])

    def test_invalid_plaintext_rolls_back_authenticated_ratchet(self):
        now = int(time.time())
        payload = dict(
            id="a" * 32,
            chat={"private": [self.a.me, self.b.me]},
            author=self.c.me,
            created=now,
            expires=now + 100,
            kind="message",
            text="forged author",
        )
        packet = self.a.secure.encrypt(self.b.me, payload, now + 100, "message")
        before = copy.deepcopy(self.b.d)
        with self.assertRaises(ValueError):
            self.b.ingest(packet)
        self.assertEqual(before, self.b.d)

    def test_bad_capability_does_not_advance_ratchet(self):
        self.a.send(self.chat, "bound proof")
        body = copy.deepcopy(self.a.d["outbox"][-1]["item"]["body"])
        body["delete_cap"]["body"]["to"] = self.c.me
        before = copy.deepcopy(self.b.d)
        with self.assertRaises(Exception):
            self.b.ingest(signed(self.a.identity, body))
        self.assertEqual(before, self.b.d)

    def test_failed_disk_write_rolls_back_send(self):
        before = copy.deepcopy(self.a.d)
        with patch.object(self.a.vault, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.a.send(self.chat, "must rollback")
        self.assertEqual(before, self.a.d)

    def test_restart_preserves_session(self):
        self.a.send(self.chat, "first")
        pump(self.engines)
        vault = MemoryVault("dummy")
        vault.data = copy.deepcopy(self.a.d)
        restored = Engine(vault)
        restored.send(self.chat, "after restart")
        pump([restored, self.b, self.c])
        self.assertEqual(self.b.d["messages"][self.chat][-1]["text"], "after restart")

    def test_simultaneous_reset(self):
        old = self.a.d["sessions"][self.b.me]["sid"]
        self.a.reset_session(self.b.me)
        self.b.reset_session(self.a.me)
        pump(self.engines)
        self.assertNotEqual(old, self.a.d["sessions"][self.b.me]["sid"])
        self.assertEqual(
            self.a.d["sessions"][self.b.me]["sid"],
            self.b.d["sessions"][self.a.me]["sid"],
        )
        self.a.send(self.chat, "reset works")
        pump(self.engines)
        self.assertEqual(self.b.d["messages"][self.chat][-1]["text"], "reset works")

    def test_old_backup_generation_recovery(self):
        low, high = sorted(self.engines[:2], key=lambda e: e.me)
        snapshot = copy.deepcopy(low.d)
        for _ in range(3):
            low.reset_session(high.me)
            pump(self.engines)
        vault = MemoryVault("dummy")
        vault.data = snapshot
        restored = Engine(vault)
        restored.reset_session(high.me)
        pump([restored, high, self.c])
        self.assertEqual(
            restored.d["sessions"][high.me]["sid"], high.d["sessions"][low.me]["sid"]
        )

    def test_private_legacy_content_rejected(self):
        item = envelope(self.a.identity, self.b.card, {}, int(time.time()) + 100)
        with self.assertRaises(ValueError):
            self.b.ingest(item)

    def test_chat_ttl_applies_to_files(self):
        self.a.files_enabled = True
        self.a.d["chat_ttl"] = {self.chat: 30 * 86400}
        self.a.send(self.chat, file_bytes=b"private", filename="file")
        m = self.a.d["messages"][self.chat][-1]
        self.assertEqual(m["expires"] - m["created"], 30 * 86400)

    def test_unsafe_received_filename_rolls_back_ratchet(self):
        for filename in (
            "../../startup.desktop",
            "C:\\startup.bat",
            "folder/file.txt",
            "file:stream",
            "NUL.txt",
            "COM¹.txt",
            "CONIN$",
            "a\x00.txt",
            "a\u202eexe.txt",
            "..",
        ):
            with self.subTest(filename=filename):
                now = int(time.time())
                payload = dict(
                    id="f" * 32,
                    chat={"private": [self.a.me, self.b.me]},
                    author=self.a.me,
                    created=now,
                    expires=now + 3600,
                    kind="file",
                    filename=filename,
                    file=enc(b"data"),
                    text="",
                )
                packet = self.a.secure.encrypt(self.b.me, payload, now + 3600, "file")
                before = copy.deepcopy(self.b.d)
                with self.assertRaises(ValueError):
                    self.b.ingest(packet)
                self.assertEqual(before, self.b.d)

    def test_unsafe_outgoing_filename_rejected(self):
        self.a.files_enabled = True
        before = copy.deepcopy(self.a.d)
        with self.assertRaises(ValueError):
            self.a.send(self.chat, file_bytes=b"data", filename="../startup.desktop")
        self.assertEqual(before, self.a.d)

    def test_group_removal_rejects_stale_membership(self):
        gid = self.a.create_group("old", [self.b.me, self.c.me])
        pump(self.engines)
        old = copy.deepcopy(self.a.d["groups"][gid])
        self.a.update_group(gid, "new", [self.b.me])
        pump(self.engines)
        self.assertEqual(self.b.d["groups"][gid]["body"]["name"], "new")
        with self.assertRaises(ValueError):
            self.c.send(gid, "removed")
        with self.assertRaises(ValueError):
            self.b.validate_chat(old, self.a.me)

    def test_group_update_only_by_creator(self):
        gid = self.a.create_group("group", [self.b.me, self.c.me])
        pump(self.engines)
        with self.assertRaises(ValueError):
            self.b.update_group(gid, "hijack", [self.a.me])

    def test_group_epoch_fork_rejected(self):
        gid = self.a.create_group("group", [self.b.me])
        pump(self.engines)
        self.a.update_group(gid, "new", [self.b.me])
        pump(self.engines)
        forged = copy.deepcopy(self.a.d["groups"][gid])
        body = forged["chain"][-1]["body"]
        body["previous"] = "0" * 64
        forged["chain"][-1] = signed(self.a.identity, body)
        forged["body"] = body
        with self.assertRaises(ValueError):
            self.b.validate_chat(forged, self.a.me)

    def test_profile_does_not_replace_identity(self):
        old = self.a.me
        self.a.update_profile("alice_new", "نام تازه")
        self.assertEqual(self.a.me, old)
        self.assertEqual(self.a.card["body"]["name"], "نام تازه")

    def test_profile_rollback_restores_identity_alias(self):
        before = copy.deepcopy(self.a.identity)
        with patch.object(self.a.vault, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.a.update_profile("alice_new", "name")
        self.assertEqual(before, self.a.identity)
        self.assertIs(self.a.identity, self.a.d["identity"])

    def test_removed_member_card_remains_for_historical_display(self):
        gid = self.a.create_group("group", [self.b.me, self.c.me])
        pump(self.engines)
        self.b.d["contacts"].pop(self.c.me)
        self.a.update_group(gid, "new", [self.b.me])
        pump(self.engines)
        self.assertEqual(self.b.peer_card(self.c.me)["body"]["id"], self.c.me)
        self.assertNotIn(self.c.me, self.b.d["contacts"])

    def test_group_scoped_member_cannot_create_unverified_new_group(self):
        self.a.create_group("first", [self.b.me, self.c.me])
        pump(self.engines)
        self.b.d["contacts"].pop(self.c.me)
        self.c.create_group("unsolicited", [self.b.me])
        item = next(
            p["item"]
            for p in self.c.d["outbox"]
            if p["item"]["body"]["to"] == self.b.me
            and p["item"]["body"]["kind"] == "group"
        )
        before = copy.deepcopy(self.b.d["sessions"][self.c.me])
        with self.assertRaises(KeyError):
            self.b.ingest(item)
        self.assertEqual(before, self.b.d["sessions"][self.c.me])

    def test_legacy_outbox_migrates_without_replacing_identity(self):
        now = int(time.time())
        payload = dict(
            id="f" * 32,
            chat={"private": sorted([self.a.me, self.b.me])},
            author=self.a.me,
            created=now,
            expires=now + 3600,
            kind="message",
            text="migrate me",
        )
        item = envelope(self.a.identity, self.b.card, payload, payload["expires"])
        vault = MemoryVault("dummy")
        vault.data = copy.deepcopy(self.a.d)
        vault.data["sessions"] = {}
        vault.data["messages"][self.chat] = [dict(payload, state="pending")]
        vault.data["outbox"] = [{"item": item, "chat": self.chat, "mid": payload["id"]}]
        migrated = Engine(vault)
        self.assertEqual(migrated.me, self.a.me)
        self.assertTrue(migrated.d["pending_secure"][self.b.me])
        self.assertTrue(
            all(p["item"]["body"]["kind"] == "session" for p in migrated.d["outbox"])
        )


class PersistenceTests(unittest.TestCase):
    def test_password_change_and_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "vault"
            v = Vault(p, "old long password", "alice", "Alice", exclusive=True)
            identity = public_card(v.data["identity"])
            with self.assertRaises(ValueError):
                Vault(p, "old long password", exclusive=True)
            v.change_password("new long password")
            v.close()
            with self.assertRaises(Exception):
                Vault(p, "old long password")
            self.assertEqual(
                public_card(Vault(p, "new long password").data["identity"]), identity
            )

    def test_case_insensitive_username_persists(self):
        a, b, _ = clients()
        with tempfile.TemporaryDirectory() as root:
            r = Relay(root)
            r.register(a.card)
            r.db.close()
            r = Relay(root)
            b.identity["username"] = a.identity["username"].upper()
            b.card = public_card(b.identity)
            with self.assertRaises(ValueError):
                r.register(b.card)
            self.assertEqual(r.live_cards, {})
            r.db.close()

    def test_clock_skew_is_bounded(self):
        a, b, _ = clients()
        chat = a.dm_id(b.me)
        now = time.time()
        with patch("mehrchat.client.time.time", return_value=now + 120):
            a.send(chat, "allowed", ttl=30 * 86400)
        with tempfile.TemporaryDirectory() as root:
            r = Relay(root)
            try:
                self.assertTrue(r.put(a.card, a.d["outbox"][-1]["item"])["ok"])
                with patch("mehrchat.client.time.time", return_value=now + 600):
                    a.send(chat, "rejected", ttl=30 * 86400)
                with self.assertRaises(ValueError):
                    r.put(a.card, a.d["outbox"][-1]["item"])
            finally:
                r.db.close()

    def test_unrelated_retraction_cannot_purge_or_block_foreign_route(self):
        a, b, c = clients()
        a.send(a.dm_id(b.me), "private")
        item = a.d["outbox"][-1]["item"]
        h = item["body"]
        with tempfile.TemporaryDirectory() as root:
            r = Relay(root)
            try:
                forged = signed(
                    c.identity,
                    dict(
                        context="MehrChat-retract-v2",
                        id=h["id"],
                        sender=c.me,
                        to=c.me,
                        expires=h["expires"],
                    ),
                )
                request = signed(
                    c.identity,
                    dict(
                        v=2,
                        kind="retract",
                        id="b" * 32,
                        sender=c.me,
                        to=c.me,
                        expires=int(time.time()) + 86400,
                        proofs=[{"card": c.card, "cap": forged}],
                    ),
                )
                r.retract(c.card, request)
                r.put(a.card, item)
                self.assertEqual(
                    r.db.execute("SELECT count(*) FROM queue").fetchone()[0], 1
                )
                foreign = copy.deepcopy(request["body"])
                foreign["proofs"] = [{"card": a.card, "cap": h["delete_cap"]}]
                with self.assertRaises(ValueError):
                    r.retract(c.card, signed(c.identity, foreign))
            finally:
                r.db.close()


class NetworkV2Tests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = legacy.NetworkTests.asyncSetUp
    asyncTearDown = legacy.NetworkTests.asyncTearDown
    channel = legacy.NetworkTests.channel
    request = legacy.NetworkTests.request

    async def test_duplicate_username_is_visible_and_failed_route_does_not_hide_connection(self):
        owner = Engine(MemoryVault("shared_name"))
        duplicate = Engine(MemoryVault("shared_name"))
        good = dict(host="127.0.0.1", port=self.port, pin=self.relay.pin)
        wrong = dict(good, pin=enc(b"x" * 32))
        owner.d["relays"] = [good, wrong]
        duplicate.d["relays"] = [good]
        tasks = []

        async def until(predicate):
            for _ in range(200):
                if predicate():
                    return
                await asyncio.sleep(0.05)
            self.fail("Connection state did not settle")

        try:
            owner.running = True
            tasks.append(asyncio.create_task(owner.loop()))
            await until(lambda: owner.status == "متصل")
            duplicate.running = True
            tasks.append(asyncio.create_task(duplicate.loop()))
            await until(lambda: duplicate.status == "نام کاربری در سرور تکراری است")
            # Let the second route fail/retry while the usable route stays open.
            for _ in range(25):
                await asyncio.sleep(0.05)
                self.assertEqual(owner.status, "متصل")
        finally:
            owner.running = duplicate.running = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_large_file_spans_noise_records(self):
        self.relay.config_path.write_text(
            json.dumps({"files_enabled": True, "max_file_bytes": 4 * 1024 * 1024})
        )
        self.a.files_enabled = True
        raw = b"private" * 170000
        chat = self.a.dm_id(self.b.me)
        self.a.send(chat, file_bytes=raw, filename="large.bin")
        ca, cb = await self.channel(self.a), await self.channel(self.b)
        self.assertTrue(
            (
                await self.request(
                    ca, {"op": "put", "item": self.a.d["outbox"][-1]["item"]}
                )
            )["ok"]
        )
        self.b.ingest((await self.request(cb, {"op": "fetch"}))["item"])
        self.assertEqual(dec(self.b.d["messages"][chat][-1]["file"]), raw)

    async def test_two_relays_replicate_and_delete_all_queued_copies(self):
        second = Relay(Path(self.tmp.name) / "second")
        server = await asyncio.start_server(second.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        a, b = Engine(MemoryVault("sender")), Engine(MemoryVault("receiver"))
        engines = [a, b]
        tasks = []
        a.add_contact(json.dumps(b.card), b.me)
        b.add_contact(json.dumps(a.card), a.me)
        routes = [
            dict(host="127.0.0.1", port=self.port, pin=self.relay.pin),
            dict(host="127.0.0.1", port=port, pin=second.pin),
        ]
        a.d["relays"] = routes
        b.d["relays"] = routes[1:]

        async def until(predicate):
            for _ in range(250):
                if predicate():
                    return
                await asyncio.sleep(0.05)
            self.fail("Relay synchronization timed out")

        try:
            for e in engines:
                e.running = True
                tasks.append(asyncio.create_task(e.loop()))
            chat = a.dm_id(b.me)
            mid = a.send(chat, "multi-relay secret")
            await until(lambda: bool(b.d["messages"].get(chat)))
            await until(lambda: a.d["messages"][chat][0]["state"] == "تحویل شد")
            b.delete(chat, mid)
            await until(lambda: not a.d["messages"][chat])
            await until(
                lambda: not any(
                    json.loads(row[0])["body"]["kind"] == "message"
                    for row in self.relay.db.execute(
                        "SELECT data FROM queue WHERE sender=? AND recipient=?",
                        (a.me, b.me),
                    ).fetchall()
                )
            )

        finally:
            for e in engines:
                e.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            server.close()
            await server.wait_closed()
            second.db.close()
