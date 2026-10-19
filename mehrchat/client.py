import asyncio
import copy
from contextlib import contextmanager
from .sessions import Sessions
from .groups import Groups
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from .crypto import (
    pack,
    public_card,
    check_card,
    signed,
    verify,
    envelope,
    open_envelope,
    enc,
    dec,
)
from .wire import connect


def safe_filename(name):
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"} | {
        prefix + number for prefix in ("COM", "LPT") for number in "123456789¹²³"
    }
    if (
        not isinstance(name, str)
        or not name
        or len(name.encode("utf-8")) > 240
        or name in (".", "..")
        or name.endswith((" ", "."))
        or name.split(".", 1)[0].rstrip(" .").upper() in reserved
        or any(
            ord(char) < 32
            or char in '<>:"/\\|?*'
            or "\u202a" <= char <= "\u202e"
            or "\u2066" <= char <= "\u2069"
            for char in name
        )
    ):
        raise ValueError("نام فایل نامعتبر است")
    return name


class Engine:
    def __init__(self, vault):
        self.vault = vault
        self.d = vault.data
        self.identity = self.d["identity"]
        self.card = public_card(self.identity)
        self.me = self.card["body"]["id"]
        self.lock = threading.RLock()
        self.status = "آفلاین"
        self.files_enabled = False
        self.running = False
        self.changed = None
        self.d.setdefault("quarantine", [])
        if isinstance(self.d["seen"], list):
            self.d["seen"] = {
                eid: int(time.time()) + 90 * 86400 for eid in self.d["seen"]
            }
        for key in (
            "delete_caps",
            "deleted_at",
            "pending_retractions",
            "lookup_results",
        ):
            self.d.setdefault(key, {})
        self.secure = Sessions(self)
        self.groups = Groups(self)
        self._depth = 0
        self.lookup_requests = []
        self.connected = {}
        self.rejected = 0
        legacy = [
            p
            for p in self.d["outbox"]
            if p["item"]["body"].get("v") == 1
            and p["item"]["body"].get("kind") != "session"
        ]
        if legacy:
            self.d["outbox"] = [p for p in self.d["outbox"] if p not in legacy]
            for entry in legacy:
                message = next(
                    (
                        m
                        for m in self.d["messages"].get(entry["chat"], [])
                        if m["id"] == entry["mid"]
                    ),
                    None,
                )
                if message and message["expires"] > time.time():
                    payload = {
                        k: v
                        for k, v in message.items()
                        if k not in ("state", "deliveries")
                    }
                    self.secure.queue(
                        entry["item"]["body"]["to"],
                        payload,
                        payload["expires"],
                        payload["kind"],
                        entry["chat"],
                        entry["mid"],
                    )

    @contextmanager
    def transaction(self):
        with self.lock:
            old = copy.deepcopy(self.d)
            self._depth += 1
            try:
                yield
                if self._depth == 1 and self.d != old:
                    self.vault.save()
            except BaseException:
                self.d.clear()
                self.d.update(old)
                self.identity = self.d["identity"]
                self.card = public_card(self.identity)
                raise
            finally:
                self._depth -= 1

    def notify(self):
        if self.changed:
            self.changed()

    def add_contact(self, text, expected_fingerprint):
        card = json.loads(text)
        b = check_card(card)
        if expected_fingerprint.replace(" ", "").lower() != b["id"]:
            raise ValueError("اثر انگشت مطابقت ندارد")
        if b["id"] == self.me:
            raise ValueError("این کارت متعلق به خودتان است")
        with self.transaction():
            self.d["contacts"][b["id"]] = card
            self.retry_quarantine()
        self.notify()
        return b["id"]

    def peer_card(self, pid):
        if pid == self.me:
            return self.card
        if pid in self.d["contacts"]:
            return self.d["contacts"][pid]
        for group in self.d["groups"].values():
            bodies = [entry["body"] for entry in reversed(group.get("chain", []))] + [
                group["body"]
            ]
            for body in bodies:
                if pid in body.get("cards", {}):
                    return body["cards"][pid]
        raise KeyError("Unknown identity")

    def dm_id(self, peer):
        return hashlib.sha256(pack(sorted([self.me, peer]))).hexdigest()

    def descriptor(self, chat):
        if chat in self.d["groups"]:
            return self.d["groups"][chat]
        peer = next((p for p in self.d["contacts"] if self.dm_id(p) == chat), None)
        if peer is None:
            raise ValueError("گفتگو پیدا نشد")
        return {"private": sorted([self.me, peer])}

    def validate_chat(self, descriptor, sender, allow_removed=False):
        return self.groups.validate(descriptor, sender, allow_removed)

    def create_group(self, name, members):
        with self.transaction():
            group = self.groups.make(name, members)
            chat = group["body"]["id"]
            self.d["groups"][chat] = group
            self.send(chat, "گروه ساخته شد", kind="group")
        return chat

    def update_group(self, chat, name, members):
        with self.transaction():
            old = self.d["groups"][chat]
            group = self.groups.make(name, members, chat)
            recipients = set(old["body"]["members"]) | set(group["body"]["members"])
            self.d["groups"][chat] = group
            now = int(time.time())
            payload = dict(
                id=uuid.uuid4().hex,
                chat=group,
                author=self.me,
                created=now,
                expires=now + 30 * 86400,
                kind="group_update",
                text="گروه به‌روزرسانی شد",
            )
            for peer in recipients - {self.me}:
                self.secure.queue(
                    peer,
                    payload,
                    payload["expires"],
                    "group_update",
                    chat,
                    payload["id"],
                )
        self.notify()

    def send(
        self,
        chat,
        text="",
        ttl=None,
        kind="message",
        file_path=None,
        file_bytes=None,
        filename=None,
    ):
        with self.transaction():
            if ttl is None:
                ttl = self.d.get("chat_ttl", {}).get(chat, self.d.get("ttl", 86400))
            if ttl not in (3600, 86400, 7 * 86400, 30 * 86400):
                raise ValueError("زمان نامعتبر است")
            descriptor = self.descriptor(chat)
            _, members, _ = self.validate_chat(descriptor, self.me)
            if len(text) > 16000:
                raise ValueError("پیام طولانی است")
            now = int(time.time())
            payload = {
                "id": uuid.uuid4().hex,
                "chat": descriptor,
                "author": self.me,
                "created": now,
                "expires": now + ttl,
                "text": text,
                "kind": kind,
            }
            if file_path or file_bytes is not None:
                if not self.files_enabled:
                    raise ValueError("ارسال فایل غیرفعال است")
                if file_path:
                    path = Path(file_path)
                    if path.stat().st_size > 4 * 1024 * 1024:
                        raise ValueError("حداکثر حجم فایل ۴ مگابایت است")
                    file_bytes, filename = path.read_bytes(), path.name
                if len(file_bytes) > 4 * 1024 * 1024:
                    raise ValueError("حداکثر حجم فایل ۴ مگابایت است")
                payload.update(
                    kind="file",
                    filename=safe_filename(filename or "file.bin"),
                    file=enc(file_bytes),
                )
            if payload["kind"] not in ("message", "file", "group"):
                raise ValueError("Invalid kind")
            for member in members:
                if member != self.me:
                    self.secure.queue(
                        member,
                        payload,
                        payload["expires"],
                        payload["kind"],
                        chat,
                        payload["id"],
                    )
            self.d["messages"].setdefault(chat, []).append(
                dict(payload, state="در انتظار ارسال")
            )
        self.notify()
        return payload["id"]

    def delete(self, chat, mid):
        with self.transaction():
            descriptor = self.descriptor(chat)
            _, members, group = self.validate_chat(descriptor, self.me)
            msg = next(
                (m for m in self.d["messages"].get(chat, []) if m["id"] == mid), None
            )
            if not msg:
                raise ValueError("پیام پیدا نشد")
            if group and msg["author"] != self.me:
                raise ValueError(
                    "در گروه فقط پیام خودتان را می‌توانید برای همه حذف کنید"
                )
            payload = {
                "id": uuid.uuid4().hex,
                "chat": descriptor,
                "author": self.me,
                "kind": "delete",
                "target": mid,
                "created": int(time.time()),
                "expires": int(time.time()) + 90 * 86400,
            }
            self.d["deleted_at"][chat + ":" + mid] = int(time.time())
            self.retract(chat, mid)
            self.d["deleted"].setdefault(chat + ":" + mid, [])
            if self.me not in self.d["deleted"][chat + ":" + mid]:
                self.d["deleted"][chat + ":" + mid].append(self.me)
            self.d["messages"][chat] = [
                m for m in self.d["messages"][chat] if m["id"] != mid
            ]
            self.d["outbox"] = [
                p
                for p in self.d["outbox"]
                if not (p["chat"] == chat and p["mid"] == mid)
            ]
            for peer, entries in self.d["pending_secure"].items():
                self.d["pending_secure"][peer] = [
                    p for p in entries if not (p["chat"] == chat and p["mid"] == mid)
                ]
            for member in members:
                if member != self.me:
                    self.secure.queue(
                        member,
                        payload,
                        payload["expires"],
                        "delete",
                        chat,
                        payload["id"],
                    )
        self.notify()

    def ingest(self, item):
        with self.transaction():
            eid = item["body"]["id"]
            if eid in self.d["seen"]:
                return
            sender = item["body"]["sender"]
            payload = self.secure.receive(item, self.peer_card(sender))
            if payload is None:
                self.d["seen"][eid] = item["body"]["expires"]
                self.retry_quarantine()
                return
            if (
                payload["author"] != sender
                or payload["kind"] != item["body"]["kind"]
                or payload["expires"] != item["body"]["expires"]
            ):
                raise ValueError("Invalid message binding")
            if (
                not isinstance(payload["created"], int)
                or payload["created"] > time.time() + 300
            ):
                raise ValueError("Invalid timestamp")
            if len(payload["id"]) != 32 or any(
                c not in "0123456789abcdef" for c in payload["id"]
            ):
                raise ValueError("Invalid message ID")
            lifetime = payload["expires"] - payload["created"]
            max_ttl = 90 * 86400 if payload["kind"] == "delete" else 30 * 86400
            if not 0 < lifetime <= max_ttl:
                raise ValueError("Invalid retention")
            chat, members, group = self.validate_chat(
                payload["chat"], sender, payload["kind"] == "group_update"
            )
            if group:
                self.d["groups"][chat] = payload["chat"]
            if payload["kind"] == "group_update":
                if not group or sender != payload["chat"]["body"]["owner"]:
                    raise ValueError("Invalid group update")
            elif payload["kind"] == "receipt":
                message = next(
                    (
                        m
                        for m in self.d["messages"].get(chat, [])
                        if m["id"] == payload["target"]
                    ),
                    None,
                )
                if message and message["author"] == self.me:
                    message.setdefault("deliveries", {})[sender] = True
                    if all(p == self.me or p in message["deliveries"] for p in members):
                        message["state"] = "تحویل شد"
            elif payload["kind"] == "delete":
                target = payload["target"]
                if len(target) != 32:
                    raise ValueError("Invalid deletion")
                key = chat + ":" + target
                # A group member cannot delete another member's message.
                existing = next(
                    (m for m in self.d["messages"].get(chat, []) if m["id"] == target),
                    None,
                )
                if group and existing and existing["author"] != sender:
                    raise ValueError("Unauthorized deletion")
                self.d["deleted_at"][key] = int(time.time())
                self.retract(chat, target)
                self.d["deleted"].setdefault(key, [])
                if sender not in self.d["deleted"][key]:
                    self.d["deleted"][key].append(sender)
                self.d["messages"][chat] = [
                    m for m in self.d["messages"].get(chat, []) if m["id"] != target
                ]
            elif payload["kind"] in ("message", "group", "file"):
                if len(payload.get("text", "")) > 16000:
                    raise ValueError("Too long")
                if payload["kind"] == "file":
                    safe_filename(payload.get("filename"))
                if (
                    payload["kind"] == "file"
                    and len(dec(payload["file"])) > 4 * 1024 * 1024
                ):
                    raise ValueError("Too large")
                actors = self.d["deleted"].get(chat + ":" + payload["id"], [])
                deleted = bool(actors) and (not group or sender in actors)
                messages = self.d["messages"].setdefault(chat, [])
                if not deleted and not any(m["id"] == payload["id"] for m in messages):
                    messages.append(dict(payload, state="دریافت شد"))
            else:
                raise ValueError("Invalid message kind")
            if payload["kind"] in ("message", "file", "group", "group_update"):
                cap = {
                    "card": self.peer_card(sender),
                    "cap": item["body"]["delete_cap"],
                }
                caps = self.d["delete_caps"].setdefault(chat + ":" + payload["id"], [])
                if cap not in caps:
                    caps.append(cap)
                receipt = dict(
                    id=uuid.uuid4().hex,
                    chat=payload["chat"],
                    author=self.me,
                    created=int(time.time()),
                    expires=min(int(time.time()) + 30 * 86400, payload["expires"]),
                    kind="receipt",
                    target=payload["id"],
                )
                if self.me in members:
                    self.secure.queue(
                        sender,
                        receipt,
                        receipt["expires"],
                        "receipt",
                        chat,
                        receipt["id"],
                    )
                if self.d["deleted"].get(chat + ":" + payload["id"]):
                    self.retract(chat, payload["id"])
            self.d["seen"][eid] = item["body"]["expires"]
        self.notify()

    def retry_quarantine(self):
        pending = self.d["quarantine"]
        self.d["quarantine"] = []
        for item in pending:
            try:
                self.ingest(item)
            except (OSError, IOError):
                raise
            except Exception:
                self.d["quarantine"].append(item)

    def prune(self):
        with self.transaction():
            now = time.time()
            self.d["pending_retractions"] = {
                k: v
                for k, v in self.d["pending_retractions"].items()
                if v["item"]["body"]["expires"] > now
            }
            self.d["seen"] = {k: v for k, v in self.d["seen"].items() if v > now}
            for key, created in list(self.d["deleted_at"].items()):
                if created + 90 * 86400 <= now:
                    self.d["deleted_at"].pop(key, None)
                    self.d["deleted"].pop(key, None)
                    self.d["delete_caps"].pop(key, None)
            for peer, pending in list(self.d["pending_secure"].items()):
                self.d["pending_secure"][peer] = [
                    p for p in pending if p["expires"] > now
                ]
            for peer, pending in list(self.d["bootstrap"].items()):
                if pending["created"] + 7 * 86400 <= now:
                    self.d["bootstrap"].pop(peer, None)
            for peer, entries in self.d["pending_secure"].items():
                if entries:
                    self.secure.ensure(peer)
            changed = False
            for chat, messages in self.d["messages"].items():
                live = [m for m in messages if m["expires"] > now]
                if len(live) != len(messages):
                    self.d["messages"][chat] = live
                    changed = True
            before = len(self.d["outbox"])
            self.d["outbox"] = [
                p for p in self.d["outbox"] if p["item"]["body"]["expires"] > now
            ]
            self.d["quarantine"] = [
                p for p in self.d["quarantine"] if p["body"]["expires"] > now
            ]
            if changed or before != len(self.d["outbox"]):
                self.notify()

    def export_file(self, chat, mid, destination):
        with self.transaction():
            msg = next(m for m in self.d["messages"][chat] if m["id"] == mid)
            if msg["expires"] <= time.time():
                raise ValueError("پیام منقضی شده است")
            path = Path(destination)
            # Explicit chosen destination; never auto-open or trust received filenames.
            with path.open("xb") as f:
                f.write(dec(msg["file"]))
            return path

    def retract(self, chat, mid):
        proofs = self.d["delete_caps"].get(chat + ":" + mid, [])
        if proofs:
            item = signed(
                self.identity,
                dict(
                    v=2,
                    kind="retract",
                    id=uuid.uuid4().hex,
                    sender=self.me,
                    to=self.me,
                    expires=int(time.time()) + 90 * 86400,
                    proofs=proofs,
                ),
            )
            self.d["pending_retractions"][chat + ":" + mid] = {
                "item": item,
                "routes": [],
            }

    def reset_session(self, peer):
        if peer not in self.d["contacts"]:
            raise ValueError("مخاطب تأیید نشده است")
        with self.transaction():
            self.secure.reset(peer)
        self.notify()

    def configure_relays(self, relays):
        if len(relays) > 5:
            raise ValueError("حداکثر ۵ سرور")
        for r in relays:
            if (
                not isinstance(r["host"], str)
                or not 1 <= int(r["port"]) <= 65535
                or len(dec(r["pin"])) != 32
            ):
                raise ValueError("مشخصات سرور معتبر نیست")
        was = self.running
        self.stop()
        if hasattr(self, "thread"):
            self.thread.join(timeout=15)
        if hasattr(self, "thread") and self.thread.is_alive():
            raise ValueError("در حال بستن اتصال")
        with self.transaction():
            self.d["relays"] = relays
        if was:
            self.start()

    def update_profile(self, username, name):
        from .crypto import create_identity

        create_identity(username, name)
        was = self.running
        self.stop()
        if hasattr(self, "thread"):
            self.thread.join(timeout=15)
        if hasattr(self, "thread") and self.thread.is_alive():
            raise ValueError("در حال بستن اتصال")
        try:
            with self.transaction():
                self.identity.update(username=username, name=name)
                self.card = public_card(self.identity)
        finally:
            if was:
                self.start()

    def lookup(self, username):
        with self.lock:
            self.lookup_requests.append(username)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()

    def _thread_main(self):
        async def run():
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()
            try:
                await self.loop()
            except asyncio.CancelledError:
                pass

        asyncio.run(run())

    async def loop(self):
        while self.running:
            relays = copy.deepcopy(self.d["relays"])
            if not relays:
                await asyncio.sleep(0.5)
                continue
            tasks = [asyncio.create_task(self.relay_loop(r)) for r in relays]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def relay_loop(self, relay):
        route = hashlib.sha256(pack(relay)).hexdigest()
        while self.running:
            channel = None
            try:
                channel = await connect(
                    relay["host"],
                    int(relay["port"]),
                    relay["pin"],
                    self.identity,
                    self.card,
                )
                self.connected[route] = False
                self.status = "متصل"
                last_settings = last_prune = 0
                while self.running:
                    now = time.monotonic()
                    if now - last_prune > 15:
                        self.prune()
                        last_prune = now
                    if now - last_settings > 5:
                        await channel.send({"op": "settings"})
                        result = await channel.recv()
                        self.connected[route] = bool(result["files_enabled"])
                        self.files_enabled = all(self.connected.values())
                        last_settings = now
                        self.notify()
                    with self.lock:
                        outgoing = copy.deepcopy(
                            [
                                p
                                for p in self.d["outbox"]
                                if route not in p.get("routes", [])
                            ][:4]
                        )
                        retractions = copy.deepcopy(
                            [
                                p
                                for p in self.d["pending_retractions"].values()
                                if route not in p.get("routes", [])
                            ][:4]
                        )
                        lookup = (
                            self.lookup_requests[0] if self.lookup_requests else None
                        )
                    for job in retractions:
                        await channel.send({"op": "retract", "item": job["item"]})
                        result = await channel.recv()
                        if result.get("ok"):
                            with self.transaction():
                                for value in self.d["pending_retractions"].values():
                                    if (
                                        value["item"]["body"]["id"]
                                        == job["item"]["body"]["id"]
                                        and route not in value["routes"]
                                    ):
                                        value["routes"].append(route)
                    for entry in outgoing:
                        await channel.send({"op": "put", "item": entry["item"]})
                        result = await channel.recv()
                        if result.get("ok") or result.get("permanent"):
                            with self.transaction():
                                current = next(
                                    (
                                        p
                                        for p in self.d["outbox"]
                                        if p["item"]["body"]["id"]
                                        == entry["item"]["body"]["id"]
                                    ),
                                    None,
                                )
                                if current:
                                    if route not in current.setdefault("routes", []):
                                        current["routes"].append(route)
                                    routes = {
                                        hashlib.sha256(pack(r)).hexdigest()
                                        for r in self.d["relays"]
                                    }
                                    if routes <= set(current["routes"]):
                                        self.d["outbox"].remove(current)
                                for m in self.d["messages"].get(entry["chat"], []):
                                    if (
                                        m["id"] == entry["mid"]
                                        and m["state"] != "تحویل شد"
                                    ):
                                        m["state"] = (
                                            "به سرور رسید"
                                            if result.get("ok")
                                            else result.get("error", "خطای ارسال")
                                        )
                            self.notify()
                        else:
                            await asyncio.sleep(0.5)
                    if lookup:
                        await channel.send({"op": "lookup", "username": lookup})
                        result = await channel.recv()
                        with self.lock:
                            self.d["lookup_results"][lookup] = result
                            if (
                                self.lookup_requests
                                and self.lookup_requests[0] == lookup
                            ):
                                self.lookup_requests.pop(0)
                        self.notify()
                    await channel.send({"op": "fetch"})
                    incoming = (await channel.recv()).get("item")
                    if incoming:
                        try:
                            self.ingest(incoming)
                        except (OSError, IOError):
                            raise
                        except KeyError:
                            with self.transaction():
                                if not any(
                                    p["body"]["id"] == incoming["body"]["id"]
                                    for p in self.d["quarantine"]
                                ):
                                    if (
                                        len(self.d["quarantine"]) < 100
                                        and sum(
                                            len(pack(p)) for p in self.d["quarantine"]
                                        )
                                        + len(pack(incoming))
                                        <= 8 * 1024 * 1024
                                    ):
                                        self.d["quarantine"].append(incoming)
                                    else:
                                        self.rejected += 1
                        except Exception:
                            self.rejected += 1
                        await channel.send({"op": "ack", "id": incoming["body"]["id"]})
                        await channel.recv()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.status = "در حال اتصال"
                self.notify()
            finally:
                self.connected.pop(route, None)
                self.files_enabled = bool(self.connected) and all(
                    self.connected.values()
                )
                if channel:
                    await channel.close()
            if self.running:
                await asyncio.sleep(1)

    def stop(self):
        self.running = False
        if getattr(self, "_loop", None) and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._task.cancel)
            except RuntimeError:
                pass
