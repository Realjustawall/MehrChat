"""One atomically replaced, authenticated encrypted file. No plaintext database."""

import json
import os
import tempfile
from pathlib import Path
from nacl.secret import SecretBox
from nacl.pwhash import argon2id
from nacl.utils import random
from .crypto import pack, enc, dec, derive, create_identity

MAGIC = b"MEHRVAULT1\0"


class Vault:
    def __init__(self, path, password, username=None, name=None, exclusive=False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lockfile = None
        if exclusive:
            self.acquire_lock()
        if self.path.exists():
            raw = self.path.read_bytes()
            if not raw.startswith(MAGIC):
                raise ValueError("Invalid vault")
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
        self.key, self.salt = key, salt
        try:
            self.save()
        except BaseException:
            self.key, self.salt = old
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
        target.write_bytes(self.path.read_bytes())
        try:
            target.chmod(0o600)
        except OSError:
            pass

    @classmethod
    def restore(cls, source, destination, password):
        # Authenticate before replacing or accepting a backup.
        source = Path(source)
        raw = source.read_bytes()
        if not raw.startswith(MAGIC):
            raise ValueError("Invalid backup")
        salt = raw[len(MAGIC) : len(MAGIC) + argon2id.SALTBYTES]
        key = derive(password, salt)
        json.loads(SecretBox(key).decrypt(raw[len(MAGIC) + argon2id.SALTBYTES :]))
        target = Path(destination)
        if target.exists():
            raise ValueError("Existing vault will not be overwritten")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(raw)
        target.chmod(0o600)
        return cls(target, password)
