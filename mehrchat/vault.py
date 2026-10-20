"""One atomically replaced, authenticated encrypted file. No plaintext database."""

import json
import os
import tempfile
from pathlib import Path
from nacl.secret import SecretBox
from nacl.pwhash import argon2id
from nacl.utils import random
from .crypto import pack, enc, dec, derive, create_identity, public_card, check_card

MAGIC = b"MEHRVAULT1\0"


class Vault:
    def __init__(self, path, password, username=None, name=None, exclusive=False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lockfile = None
        if exclusive:
            self.acquire_lock()
        try:
            if self.path.exists():
                raw = self.path.read_bytes()
                if not raw.startswith(MAGIC):
                    raise ValueError("فایل حساب معتبر نیست")
                self.salt = raw[len(MAGIC) : len(MAGIC) + argon2id.SALTBYTES]
                self.key = derive(password, self.salt)
                self.data = json.loads(
                    SecretBox(self.key).decrypt(raw[len(MAGIC) + argon2id.SALTBYTES :])
                )
            else:
                self.salt = random(argon2id.SALTBYTES)
                self.key = derive(password, self.salt)
                self.data = {
                    "identity": create_identity(username, name),
                    "contacts": {},
                    "groups": {},
                    "messages": {},
                    "outbox": [],
                    "seen": [],
                    "deleted": {},
                    "relays": [],
                }
                self.save()
        except BaseException:
            # An exception's traceback can retain this instance. Release explicitly
            # so a wrong password never prevents the next correct login.
            if self._lockfile is not None:
                self._lockfile.close()
                self._lockfile = None
            raise

    def acquire_lock(self):
        if self._lockfile is not None:
            return
        stream = self.path.with_suffix(".lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0, 2)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lockfile = stream
        except OSError as exc:
            stream.close()
            raise ValueError("این حساب در یک پنجره دیگر باز است") from exc

    def save(self):
        raw = MAGIC + self.salt + bytes(SecretBox(self.key).encrypt(pack(self.data)))
        fd, temp = tempfile.mkstemp(
            prefix=".vault-", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass

    def change_password(self, password):
        salt = random(argon2id.SALTBYTES)
        key = derive(password, salt)
        old = self.key, self.salt
        previous_backup = self.data.get("backup_last_at")
        self.key, self.salt = key, salt
        self.data["backup_last_at"] = 0
        try:
            self.save()
        except BaseException:
            self.key, self.salt = old
            if previous_backup is None:
                self.data.pop("backup_last_at", None)
            else:
                self.data["backup_last_at"] = previous_backup
            raise

    def close(self):
        if self._lockfile is not None:
            self._lockfile.close()
            self._lockfile = None
        self.key = b""
        for key in ("sign_secret", "box_secret"):
            self.data.get("identity", {}).pop(key, None)
        self.data.clear()

    def __del__(self):
        stream = getattr(self, "_lockfile", None)
        if stream is not None:
            stream.close()

    def backup(self, destination):
        self.save()
        target = Path(destination)
        if target.resolve() == self.path.resolve():
            raise ValueError("Choose a different backup path")
        # Never replace an existing backup or another account by accident.
        stream = target.open("xb")
        try:
            with stream:
                if os.name != "nt":
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(self.path.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    @classmethod
    def restore(cls, source, destination, password):
        with Path(source).open("rb") as stream:
            raw = stream.read(128 * 1024 * 1024 + 1)
        return cls.restore_bytes(raw, destination, password)

    @classmethod
    def restore_bytes(cls, raw, destination, password):
        # Authenticate before publication, then retain the destination account lock.
        # A private staging filename alone does not lock the live account path.
        if len(raw) > 128 * 1024 * 1024:
            raise ValueError("حجم پشتیبان بیش از حد مجاز است")
        if not raw.startswith(MAGIC):
            raise ValueError("فایل پشتیبان معتبر نیست")
        salt = raw[len(MAGIC) : len(MAGIC) + argon2id.SALTBYTES]
        key = derive(password, salt)
        data = json.loads(SecretBox(key).decrypt(raw[len(MAGIC) + argon2id.SALTBYTES :]))
        check_card(public_card(data["identity"]))
        for field in ("contacts", "groups", "messages", "deleted"):
            if not isinstance(data.get(field), dict):
                raise ValueError("اطلاعات پشتیبان معتبر نیست")
        for field in ("outbox", "relays"):
            if not isinstance(data.get(field), list):
                raise ValueError("اطلاعات پشتیبان معتبر نیست")
        if not isinstance(data.get("seen"), (dict, list)):
            raise ValueError("اطلاعات پشتیبان معتبر نیست")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        restored = cls.__new__(cls)
        restored.path, restored._lockfile = target, None
        restored.key, restored.salt, restored.data = key, salt, data
        try:
            restored.acquire_lock()
            if target.exists():
                raise ValueError("حساب موجود است؛ بازیابی روی آن انجام نمی‌شود")
            restored.save()
            return restored
        except BaseException:
            restored.close()
            raise
