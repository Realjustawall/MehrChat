import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread, Lock
from .crypto import create_identity, public_card, check_card, verify, pack
from .wire import accept
from .limits import AdmissionLimiter

# A 4 MiB attachment is base64 inside encrypted JSON and the ciphertext is
# base64 again. Allow the signed 32-member/64-epoch descriptor as well.
MAX_CIPHER = 12 * 1024 * 1024
MAX_CONTROL_CIPHER = 4 * 1024 * 1024
CLOCK_SKEW = 300
MAX_USERS = 100000
MAX_RETRACTIONS = 500000
MAX_ROUTE_RETRACTIONS = 10000


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
        self.admin_credentials = self.root / 'admin-account.json'
        self.admin_limiter = AdmissionLimiter(rate=0.2, burst=5, capacity=1)
        self.admin_lock = Lock()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS retractions (id TEXT, sender TEXT, recipient TEXT, expires INTEGER, PRIMARY KEY(id,sender,recipient))"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS retraction_route ON retractions(sender,recipient)")
        self.db.commit()
        self.live_cards = {}
        self.active = set()
        self.connections = 0
        self.events = {}
        self.admission = AdmissionLimiter()
        self.global_admission = AdmissionLimiter(rate=8, burst=64, capacity=1)

    def register(self, card):
        b = check_card(card)
        if (not self.db.execute("SELECT 1 FROM users WHERE id=?", (b["id"],)).fetchone()
                and self.db.execute("SELECT count(*) FROM users").fetchone()[0] >= MAX_USERS):
            raise ValueError("Registration capacity reached")
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO users(id,username) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username",
                    (b["id"], b["username"].lower()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("این نام کاربری قبلاً ثبت شده است") from exc

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
            for cap in verified:
                existing = self.db.execute(
                    "SELECT 1 FROM retractions WHERE id=? AND sender=? AND recipient=?",
                    (cap["id"], cap["sender"], cap["to"]),
                ).fetchone()
                if not existing:
                    total = self.db.execute("SELECT count(*) FROM retractions").fetchone()[0]
                    route = self.db.execute(
                        "SELECT count(*) FROM retractions WHERE sender=? AND recipient=?",
                        (cap["sender"], cap["to"]),
                    ).fetchone()[0]
                    if total >= MAX_RETRACTIONS or route >= MAX_ROUTE_RETRACTIONS:
                        raise ValueError("Retraction capacity reached")
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

    def authenticate_admin(self, values):
        with self.admin_lock:
            if not self.admin_limiter.allow('admin'):
                return False
        if self.admin_credentials.exists():
            from nacl.pwhash import argon2id
            from nacl.exceptions import InvalidkeyError
            account = json.loads(self.admin_credentials.read_text())
            username, password = values.get('username', [''])[0], values.get('password', [''])[0]
            if not hmac.compare_digest(username.encode(), account['username'].encode()) or len(password) > 1024:
                return False
            try:
                return argon2id.verify(account['password_hash'].encode(), password.encode())
            except (InvalidkeyError, ValueError):
                return False
        return hmac.compare_digest(values.get('token', [''])[0].encode(), self.admin_token.encode())

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
        peer = writer.get_extra_info("peername")
        address = str(peer[0]) if peer else "unknown"
        if (self.connections >= 64 or not self.global_admission.allow("all")
                or not self.admission.allow(address)):
            writer.close()
            return
        self.connections += 1
        user = None
        try:
            channel, card = await asyncio.wait_for(
                accept(reader, writer, self.identity, self.register, allow_probe=True), 15
            )
            if card is None:
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
                        "card": self.live_cards.get(row[0]) if row else None,
                        "online": bool(row and row[0] in self.live_cards),
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

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def end_headers(self):
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                super().end_headers()

            def english(self):
                from urllib.parse import parse_qs, urlsplit
                return parse_qs(urlsplit(self.path).query).get("lang") == ["en"]

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
<h1>تنظیمات سرور</h1><form method="post"><p>رمز مدیریت</p><input type="password" name="token" required autocomplete="off"><p><label><input type="checkbox" name="files" value="yes">فعال‌سازی ارسال فایل</label></p><button>ذخیره</button></form><p>حداکثر حجم فایل: ۴ مگابایت</p></html>"""
                if relay.settings()["files_enabled"]:
                    html = html.replace('value="yes"', 'value="yes" checked')
                if relay.admin_credentials.exists():
                    html = html.replace('<p>رمز مدیریت</p><input type="password" name="token" required autocomplete="off">', '<p>Admin username / نام کاربری مدیر</p><input name="username" required autocomplete="username"><p>Admin password / رمز مدیر</p><input type="password" name="password" required autocomplete="current-password">')
                html += '<p><a href="/?lang=fa">فارسی</a> | <a href="/?lang=en">English</a></p>'
                if self.english():
                    for fa, en in {
                        'lang="fa" dir="rtl"': 'lang="en" dir="ltr"',
                        'مدیریت مهر': 'Mehr administration', 'تنظیمات سرور': 'Relay settings',
                        'رمز مدیریت': 'Admin token', 'فعال‌سازی ارسال فایل': 'Enable file transfers',
                        'ذخیره': 'Save', 'حداکثر حجم فایل: ۴ مگابایت': 'Maximum file size: 4 MiB',
                    }.items():
                        html = html.replace(fa, en)
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

                try:
                    n = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self.send_error(400)
                    return
                if not 0 < n <= 4096:
                    self.send_error(400)
                    return
                try:
                    values = parse_qs(self.rfile.read(n).decode(), max_num_fields=4)
                except (UnicodeError, ValueError):
                    self.send_error(400)
                    return
                if not relay.authenticate_admin(values):
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
                self.wfile.write(b"Saved" if self.english() else "ذخیره شد".encode())

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        return server


async def run(args):
    relay = Relay(args.data)
    config_path = relay.root / 'deployment.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    tls = config.get('tls')
    context = None
    tls_pin = None
    if tls:
        from .tls import server_context
        from .tls import public_key_pin
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        context = server_context(tls['cert'], tls['key'])
        tls_pin = public_key_pin(x509.load_pem_x509_certificate(Path(tls['cert']).read_bytes()).public_bytes(serialization.Encoding.DER))
    if config.get('port'):
        args.port = config['port']
    (relay.root / "relay-public.json").write_text(
        json.dumps(
            {
                "transport": "Noise_NK_25519_ChaChaPoly_SHA256",
                "port": args.port,
                "pin": relay.pin,
                'tls': bool(tls),
                'tls_pin': tls_pin,
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
    server = await asyncio.start_server(relay.handle, args.host, args.port, **({'ssl': context, 'ssl_handshake_timeout': 12} if context else {}))

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
    parser.add_argument('--setup', action='store_true', help='Interactive Ubuntu deployment configuration')
    args = parser.parse_args()
    if args.setup:
        from .setup import configure
        configure(args.data)
        return
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
