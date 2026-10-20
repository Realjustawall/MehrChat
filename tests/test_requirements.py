"""Behavioral regressions for identity survival and sender-controlled retention."""

import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox

from test_security import clients, pump
from mehrchat.crypto import pack, public_card
from mehrchat.vault import MAGIC, Vault

PASSWORD = "account backup test password"


class BackupSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = Vault(self.root / "original.mcv", PASSWORD, "alice", "علی")
        self.addCleanup(self.vault.close)
        self.raw = self.vault.path.read_bytes()

    def test_restored_account_keeps_destination_lock_until_closed(self):
        target = self.root / "restored.mcv"
        restored = Vault.restore_bytes(self.raw, target, PASSWORD)
        try:
            self.assertEqual(public_card(restored.data["identity"]), public_card(self.vault.data["identity"]))
            with self.assertRaisesRegex(ValueError, "پنجره"):
                Vault(target, PASSWORD, exclusive=True)
        finally:
            restored.close()
        reopened = Vault(target, PASSWORD, exclusive=True)
        reopened.close()

    def test_restore_refuses_live_destination_even_when_file_is_absent(self):
        target = self.root / "restored.mcv"
        live = Vault(target, PASSWORD, "bobby", "رضا", exclusive=True)
        try:
            target.unlink()
            with self.assertRaisesRegex(ValueError, "پنجره"):
                Vault.restore_bytes(self.raw, target, PASSWORD)
            self.assertFalse(target.exists())
        finally:
            live.close()

    def test_restore_cannot_overwrite_another_identity(self):
        before = self.vault.path.read_bytes()
        with self.assertRaises(ValueError):
            Vault.restore_bytes(self.raw, self.vault.path, PASSWORD)
        self.assertEqual(before, self.vault.path.read_bytes())

    def test_wrong_password_and_tamper_publish_nothing(self):
        target = self.root / "restored.mcv"
        for raw, password in ((self.raw, "another wrong password"), (self.raw[:-1] + bytes([self.raw[-1] ^ 1]), PASSWORD)):
            with self.assertRaises(CryptoError):
                Vault.restore_bytes(raw, target, password)
            self.assertFalse(target.exists())

    def test_authenticated_invalid_state_is_not_published(self):
        data = copy.deepcopy(self.vault.data)
        data["contacts"] = []
        raw = MAGIC + self.vault.salt + bytes(SecretBox(self.vault.key).encrypt(pack(data)))
        target = self.root / "bad.mcv"
        with self.assertRaises(ValueError):
            Vault.restore_bytes(raw, target, PASSWORD)
        self.assertFalse(target.exists())

    def test_restore_disk_failure_releases_lock_for_retry(self):
        target = self.root / "restored.mcv"
        with patch.object(Vault, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                Vault.restore_bytes(self.raw, target, PASSWORD)
        restored = Vault.restore_bytes(self.raw, target, PASSWORD)
        restored.close()

    def test_failed_login_releases_lock_even_with_retained_traceback(self):
        retained = None
        try:
            Vault(self.vault.path, "wrong password but long", exclusive=True)
        except CryptoError as exc:
            retained = exc
        self.assertIsNotNone(retained)
        reopened = Vault(self.vault.path, PASSWORD, exclusive=True)
        reopened.close()

    def test_backup_never_overwrites_existing_file(self):
        target = self.root / "backup.mcv"
        target.write_bytes(b"an existing important file")
        with self.assertRaises(FileExistsError):
            self.vault.backup(target)
        self.assertEqual(target.read_bytes(), b"an existing important file")

    def test_backup_failure_does_not_leave_partial_backup(self):
        target = self.root / "backup.mcv"
        # The source save must succeed; fail the destination backup's fsync.
        original_save = self.vault.save
        original_save()
        with patch.object(self.vault, "save"), patch("mehrchat.vault.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.vault.backup(target)
        self.assertFalse(target.exists())

    def test_password_change_invalidates_backup_reminder_atomically(self):
        self.vault.data["backup_last_at"] = 123
        with patch.object(self.vault, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.vault.change_password("a new long password")
        self.assertEqual(self.vault.data["backup_last_at"], 123)
        self.vault.change_password("a new long password")
        self.assertEqual(self.vault.data["backup_last_at"], 0)


class RequestedBehaviorTests(unittest.TestCase):
    def test_expired_file_cannot_be_saved_even_before_next_prune(self):
        a, b, c = clients()
        chat = a.dm_id(b.me)
        a.files_enabled = True
        mid = a.send(chat, file_bytes=b"private file", filename="document.txt", ttl=3600)
        pump([a, b, c])
        self.assertEqual(b.read_file(chat, mid), b"private file")
        with patch("mehrchat.client.time.time", return_value=time.time() + 3601):
            with self.assertRaises(ValueError):
                b.read_file(chat, mid)
        b.delete(chat, mid)
        with self.assertRaises(ValueError):
            b.read_file(chat, mid)

    def test_each_retention_option_expires_on_both_devices_while_offline(self):
        for ttl in (3600, 86400, 7 * 86400, 30 * 86400):
            with self.subTest(ttl=ttl):
                a, b, c = clients()
                chat = a.dm_id(b.me)
                a.d["chat_ttl"] = {chat: ttl}
                mid = a.send(chat, "زمان را فرستنده تعیین می‌کند")
                pump([a, b, c])
                received = next(m for m in b.d["messages"][chat] if m["id"] == mid)
                self.assertEqual(received["expires"] - received["created"], ttl)
                with patch("mehrchat.client.time.time", return_value=received["expires"] + 1):
                    a.prune()
                    b.prune()
                self.assertFalse(a.d["messages"][chat])
                self.assertFalse(b.d["messages"][chat])
                self.assertFalse(a.d["outbox"])
                self.assertFalse(b.d["outbox"])

    def test_either_private_participant_can_delete_messages_from_both_authors(self):
        for delete_by_sender in (False, True):
            with self.subTest(delete_by_sender=delete_by_sender):
                engines = clients()
                a, b, _ = engines
                chat = a.dm_id(b.me)
                first = a.send(chat, "پیام علی")
                second = b.send(chat, "پیام رضا")
                pump(engines)
                actor = a if delete_by_sender else b
                actor.delete(chat, first)
                actor.delete(chat, second)
                pump(engines)
                self.assertEqual(a.d["messages"][chat], [])
                self.assertEqual(b.d["messages"][chat], [])

    def test_every_group_member_can_send_and_delete_own_message_for_all(self):
        engines = clients()
        a, b, c = engines
        chat = a.create_group("دوستان", [b.me, c.me])
        pump(engines)
        for author in engines:
            mid = author.send(chat, "سلام از " + author.identity["name"])
            pump(engines)
            for receiver in engines:
                self.assertTrue(any(m["id"] == mid for m in receiver.d["messages"][chat]))
            author.delete(chat, mid)
            pump(engines)
            for receiver in engines:
                self.assertFalse(any(m["id"] == mid for m in receiver.d["messages"][chat]))
