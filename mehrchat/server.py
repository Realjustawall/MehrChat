import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import ssl
import sqlite3
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from .crypto import create_identity, public_card, check_card, verify, pack
from .wire import accept, ReceiveBudget
from .contact_invite import address, normalize

# A 4 MiB attachment is base64 inside encrypted JSON and the ciphertext is
# base64 again. Allow the signed 32-member/64-epoch descriptor as well.
MAX_CIPHER = 12 * 1024 * 1024
MAX_CONTROL_CIPHER = 4 * 1024 * 1024
CLOCK_SKEW = 300
MAX_USERS = 10000
MAX_DIRECTORY_BYTES = 16 * 1024 * 1024
MAX_SEEN = 100000
MAX_RETRACTIONS = 100000
MAX_CONNECTIONS_PER_IP = 16


class Relay:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        keyfile = self.root / "transport-key.json"
        if not keyfile.exists():
            keyfile.write_text(json.dumps(create_identity("relay", "Relay")))
            keyfile.chmod(0o600)
        self.identity = json.loads(keyfile.read_text())
        self.pin = public_card(self.identity)["body"]["box"]
        self.db = sqlite3.connect(self.root / "queue.sqlite")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS queue (id TEXT PRIMARY KEY, recipient TEXT, sender TEXT, expires INTEGER, data BLOB)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS inbox ON queue(recipient,expires)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, expires INTEGER)"
        )
        self.config_path = self.root / "settings.json"
        if not self.config_path.exists():
            self.config_path.write_text(
                json.dumps({"files_enabled": False, "max_file_bytes": 4 * 1024 * 1024})
            )
        tokenfile = self.root / "admin-token.txt"
        if not tokenfile.exists():
            tokenfile.write_text(secrets.token_urlsafe(32))
            tokenfile.chmod(0o600)
        self.admin_token = tokenfile.read_text().strip()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS retractions (id TEXT, sender TEXT, recipient TEXT, expires INTEGER, PRIMARY KEY(id,sender,recipient))"
        )
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(users)')}
        for name in ('share_address', 'public_card'):
            if name not in columns:
                self.db.execute('ALTER TABLE users ADD COLUMN ' + name + ' TEXT')
        self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS share_address ON users(share_address)')
        self.db.commit()
        self.live_cards = {}
        self.active = set()
        self.connections = 0
        self.events = {}
        self.receive_budget = ReceiveBudget()
        self.ip_connections = {}
        self.registration_tokens = 60.0
        self.registration_last = time.monotonic()

    def register(self, card):
        b = check_card(card)
        raw = json.dumps(card)
        previous = self.db.execute('SELECT length(CAST(public_card AS BLOB)) FROM users WHERE id=?', (b['id'],)).fetchone()
        count, size = self.db.execute('SELECT count(*),coalesce(sum(length(CAST(public_card AS BLOB))),0) FROM users').fetchone()
        if (previous is None and count >= MAX_USERS) or size - ((previous[0] or 0) if previous else 0) + len(raw.encode()) > MAX_DIRECTORY_BYTES:
            raise ValueError("Public directory quota exceeded")
        if previous is None:
            now = time.monotonic()
            self.registration_tokens = min(60.0, self.registration_tokens + (now - self.registration_last) / 6)
            self.registration_last = now
            if self.registration_tokens < 1:
                raise ValueError("Registration rate limited")
            self.registration_tokens -= 1
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO users(id,username,share_address,public_card) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,share_address=excluded.share_address,public_card=excluded.public_card",
                    (b["id"], b["username"].lower(), "".join(address(card)), raw),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("این نام کاربری قبلاً ثبت شده است") from exc

    def lookup_address(self, number, code):
        number, code = normalize(number, code)
        row = self.db.execute('SELECT public_card FROM users WHERE share_address=?', (number + code,)).fetchone()
        return {'ok': True, 'card': json.loads(row[0]) if row and row[0] else None}

    def retract(self, card, item):
        request = verify(card, item)
        user = check_card(card)["id"]
        now = time.time()
        if (
            request.get("v") != 2
            or request.get("kind") != "retract"
            or request.get("sender") != user
            or request.get("to") != user
            or not now < request.get("expires", 0) <= now + 90 * 86400 + CLOCK_SKEW
        ):
            raise ValueError("Invalid retraction")
        proofs = request["proofs"]
        if not isinstance(proofs, list) or not 1 <= len(proofs) <= 64:
            raise ValueError("Invalid proofs")
        verified = []
        for p in proofs:
            b = check_card(p["card"])
            cap = verify(p["card"], p["cap"])
            if (
                cap.get("context") != "MehrChat-retract-v2"
                or cap.get("sender") != b["id"]
                or user not in (cap["sender"], cap["to"])
            ):
                raise ValueError("Unauthorized retraction")
            if (
                not isinstance(cap["id"], str)
                or len(cap["id"]) != 32
                or any(c not in "0123456789abcdef" for c in cap["id"])
            ):
                raise ValueError("Invalid envelope")
            verified.append(cap)
        with self.db:
            # Bound retained tombstones independently of the ciphertext queue.
            additional = sum(not self.db.execute('SELECT 1 FROM retractions WHERE id=? AND sender=? AND recipient=?',
                             (cap['id'], cap['sender'], cap['to'])).fetchone() for cap in verified)
            if self.db.execute('SELECT count(*) FROM retractions').fetchone()[0] + additional > MAX_RETRACTIONS:
                raise ValueError("Retraction quota exceeded")
            for cap in verified:
                self.db.execute(
                    "DELETE FROM queue WHERE id=? AND sender=? AND recipient=?",
                    (cap["id"], cap["sender"], cap["to"]),
                )
                self.db.execute(
                    "INSERT INTO retractions VALUES(?,?,?,?) ON CONFLICT(id,sender,recipient) DO UPDATE SET expires=max(expires,excluded.expires)",
                    (
                        cap["id"],
                        cap["sender"],
                        cap["to"],
                        min(request["expires"], int(now) + 90 * 86400),
                    ),
                )
        return {"ok": True}

    def settings(self):
        return json.loads(self.config_path.read_text())

    def cleanup(self):
        now = time.time()
        self.db.execute("DELETE FROM queue WHERE expires <= ?", (now,))
        self.db.execute("DELETE FROM seen WHERE expires <= ?", (now,))
        self.db.execute("DELETE FROM retractions WHERE expires <= ?", (now,))
        self.db.commit()

    def put(self, card, item):
        body = verify(card, item)
        now = time.time()
        if body.get("v") not in (1, 2) or body["sender"] != check_card(card)["id"]:
            raise ValueError("Invalid sender")
        if (
            not isinstance(body["to"], str)
            or len(body["to"]) != 64
            or any(c not in "0123456789abcdef" for c in body["to"])
        ):
            raise ValueError("Invalid recipient")
        if len(body["id"]) != 32 or any(
            c not in "0123456789abcdef" for c in body["id"]
        ):
            raise ValueError("Invalid ID")
        if (
            not isinstance(body["expires"], int)
            or not now < body["expires"] <= now + 90 * 86400 + CLOCK_SKEW
        ):
            raise ValueError("Invalid expiry")
        if body["kind"] not in (
            "message",
            "delete",
            "group",
            "group_update",
            "file",
            "session",
            "receipt",
        ):
            raise ValueError("Invalid kind")
        if body["kind"] != "delete" and body["expires"] > now + 30 * 86400 + CLOCK_SKEW:
            raise ValueError("Expiry exceeds 30 days")
        if body["v"] == 1 and body["kind"] != "session":
            raise ValueError("Legacy content disabled")
        if body["kind"] in ("message", "file", "group", "group_update"):
            cap = verify(card, body["delete_cap"])
            if cap != dict(
                context="MehrChat-retract-v2",
                id=body["id"],
                sender=body["sender"],
                to=body["to"],
                expires=body["expires"],
            ):
                raise ValueError("Invalid deletion proof")
        conf = self.settings()
        if body["kind"] == "file" and not conf["files_enabled"]:
            return {"ok": False, "error": "ارسال فایل غیرفعال است", "permanent": True}
        raw = pack(item)
        limit = (
            MAX_CIPHER
            if body["kind"] == "file" and conf["files_enabled"]
            else MAX_CONTROL_CIPHER
        )
        if len(raw) > limit:
            raise ValueError("Packet too large")
        if self.db.execute(
            "SELECT 1 FROM retractions WHERE id=? AND sender=? AND recipient=? AND expires>?",
            (body["id"], body["sender"], body["to"], now),
        ).fetchone():
            return {"ok": True}
        # Idempotent retry after lost response, including already acknowledged IDs.
        if self.db.execute("SELECT 1 FROM seen WHERE id=?", (body["id"],)).fetchone():
            return {"ok": True}
        rows, total = self.db.execute(
            "SELECT count(*),coalesce(sum(length(data)),0) FROM queue WHERE recipient=?",
            (body["to"],),
        ).fetchone()
        overall = self.db.execute(
            "SELECT coalesce(sum(length(data)),0) FROM queue"
        ).fetchone()[0]
        if (
            rows >= 2000
            or total + len(raw) > 64 * 1024 * 1024
            or overall + len(raw) > 1024 * 1024 * 1024
        ):
            return {"ok": False, "error": "صندوق پیام پر است"}
        if self.db.execute('SELECT count(*) FROM seen').fetchone()[0] >= MAX_SEEN:
            return {"ok": False, "error": "Relay receipt quota exceeded"}
        with self.db:
            self.db.execute(
                "INSERT INTO queue VALUES(?,?,?,?,?)",
                (body["id"], body["to"], body["sender"], body["expires"], raw),
            )
            self.db.execute(
                "INSERT INTO seen VALUES(?,?)", (body["id"], body["expires"])
            )
        if body["to"] in self.events:
            self.events[body["to"]].set()
        return {"ok": True}

    async def handle(self, reader, writer):
        peer = writer.get_extra_info('peername')
        ip = peer[0] if peer else 'unknown'
        if self.connections >= 64 or self.ip_connections.get(ip, 0) >= MAX_CONNECTIONS_PER_IP:
            writer.close()
            return
        self.connections += 1
        self.ip_connections[ip] = self.ip_connections.get(ip, 0) + 1
        user = None
        try:
            channel, card = await asyncio.wait_for(
                accept(reader, writer, self.identity, self.register, self.receive_budget), 15
            )
            if card is None:  # Authenticated pre-login probe; never register an account.
                return
            user = check_card(card)["id"]
            if user in self.active:
                user = None
                return
            self.active.add(user)
            self.live_cards[user] = card
            self.events[user] = asyncio.Event()
            tokens, last = 120.0, time.monotonic()
            while True:
                request = await channel.recv()
                schemas = {'put': {'op', 'item'}, 'retract': {'op', 'item'},
                           'lookup_code': {'op', 'number', 'code'}, 'lookup': {'op', 'username'},
                           'fetch': {'op'}, 'ack': {'op', 'id'}, 'settings': {'op'}}
                if (not isinstance(request, dict) or not isinstance(request.get('op'), str)
                        or set(request) != schemas.get(request['op'])):
                    raise ValueError('Invalid request fields')
                now = time.monotonic()
                tokens = min(120.0, tokens + (now - last) * 20)
                last = now
                if tokens < 1:
                    raise ValueError("Rate limited")
                tokens -= 1
                self.cleanup()
                op = request.get("op")
                if op == "put":
                    result = self.put(card, request["item"])
                elif op == "retract":
                    result = self.retract(card, request["item"])
                elif op == "lookup_code":
                    result = self.lookup_address(request.get("number", ""), request.get("code", ""))
                elif op == "lookup":
                    username = request.get("username", "")
                    if not isinstance(username, str) or len(username) > 32:
                        raise ValueError("Invalid username")
                    row = self.db.execute(
                        "SELECT id FROM users WHERE username=?", (username.lower(),)
                    ).fetchone()
                    result = {
                        "ok": True,
                        "id": row[0] if row else None,
                        # A public username reservation is not a presence oracle.
                        # Full cards require the key-bound contact address.
                        "card": None,
                    }
                elif op == "fetch":
                    row = self.db.execute(
                        "SELECT data FROM queue WHERE recipient=? AND expires>? ORDER BY rowid LIMIT 1",
                        (user, time.time()),
                    ).fetchone()
                    if row is None:
                        self.events[user].clear()
                        try:
                            await asyncio.wait_for(self.events[user].wait(), 0.15)
                        except asyncio.TimeoutError:
                            pass
                        row = self.db.execute(
                            "SELECT data FROM queue WHERE recipient=? AND expires>? ORDER BY rowid LIMIT 1",
                            (user, time.time()),
                        ).fetchone()
                    result = {"ok": True, "item": json.loads(row[0]) if row else None}
                elif op == "ack":
                    with self.db:
                        self.db.execute(
                            "DELETE FROM queue WHERE id=? AND recipient=?",
                            (request["id"], user),
                        )
                    result = {"ok": True}
                elif op == "settings":
                    result = dict(self.settings(), ok=True)
                else:
                    raise ValueError("Unknown operation")
                await channel.send(result)
        except (Exception, asyncio.CancelledError):
            # Never log user packets, identities, message bodies or keys.
            pass
        finally:
            self.connections -= 1
            self.ip_connections[ip] -= 1
            if not self.ip_connections[ip]:
                del self.ip_connections[ip]
            if user:
                self.active.discard(user)
                self.live_cards.pop(user, None)
                self.events.pop(user, None)
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass

    def start_admin(self, port=8788):
        relay = self
        from threading import Lock
        from .deployment import verify_admin
        attempts = []
        attempt_lock = Lock()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path == "/font.ttf":
                    raw = (
                        Path(__file__).resolve().parent.parent
                        / "assets/Vazirmatn-Regular.ttf"
                    ).read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "font/ttf")
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                html = """<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>مدیریت مهر</title>
<style>@font-face{font-family:Vazirmatn;src:url('/font.ttf')}body{font-family:Vazirmatn,sans-serif;background:#17212b;color:#fff;font-size:18px;max-width:620px;margin:70px auto}input,button{font:inherit;padding:14px;margin:10px}</style>
<h1>تنظیمات سرور</h1><form method="post"><p>نام کاربری مدیر</p><input name="username" autocomplete="username"><p>رمز مدیریت</p><input type="password" name="token" required autocomplete="off"><p><label><input type="checkbox" name="files" value="yes">فعال‌سازی ارسال فایل</label></p><button>ذخیره</button></form><p>حداکثر حجم فایل: ۴ مگابایت</p></html>"""
                if relay.settings()["files_enabled"]:
                    html = html.replace('value="yes"', 'value="yes" checked')
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; font-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(html.encode())

            def do_POST(self):
                from urllib.parse import parse_qs

                with attempt_lock:
                    now = time.monotonic()
                    attempts[:] = [t for t in attempts if now - t < 60]
                    if len(attempts) >= 10:
                        self.send_error(429)
                        return
                    attempts.append(now)
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self.send_error(400)
                    return
                if not 0 < n <= 4096:
                    self.send_error(400)
                    return
                values = parse_qs(self.rfile.read(n).decode())
                password = values.get("token", [""])[0]
                if (relay.root / "admin-credentials.json").exists():
                    allowed = verify_admin(relay.root, values.get("username", [""])[0], password)
                else:
                    allowed = hmac.compare_digest(password, relay.admin_token)
                if not allowed:
                    self.send_error(403)
                    return
                conf = relay.settings()
                conf["files_enabled"] = values.get("files") == ["yes"]
                temp = relay.config_path.with_suffix(".tmp")
                temp.write_text(json.dumps(conf))
                os.replace(temp, relay.config_path)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write("ذخیره شد".encode())

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        return server


async def run(args):
    relay = Relay(args.data)
    (relay.root / "relay-public.json").write_text(
        json.dumps(
            {
                "transport": "Noise_NK_25519_ChaChaPoly_SHA256",
                "port": args.port,
                "pin": relay.pin,
            }
        )
    )
    print("Server public pin:", relay.pin, flush=True)
    print(
        "Admin: http://127.0.0.1:%d ; token file: %s"
        % (args.admin_port, relay.root / "admin-token.txt"),
        flush=True,
    )
    relay.start_admin(args.admin_port)
    context = None
    if bool(args.tls_cert) != bool(args.tls_key):
        raise ValueError("Both --tls-cert and --tls-key are required")
    if args.tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_cert, args.tls_key)
    server = await asyncio.start_server(relay.handle, args.host, args.port, ssl=context,
                                        **({"ssl_handshake_timeout": 12} if context else {}))

    async def sweep():
        while True:
            relay.cleanup()
            await asyncio.sleep(30)

    task = asyncio.create_task(sweep())
    try:
        async with server:
            await server.serve_forever()
    finally:
        task.cancel()
        relay.db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--admin-port", type=int, default=8788)
    parser.add_argument("--data", default="relay-data")
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
