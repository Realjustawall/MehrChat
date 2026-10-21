"""Identity-signed ephemeral bootstrap and persistent pairwise ratchets."""

import hashlib, json, time, uuid
from . import ratchet
from .crypto import envelope, open_envelope, check_card, verify, signed, enc, dec, pack


class Sessions:
    def __init__(self, engine):
        self.e = engine
        for key in ("sessions", "bootstrap", "pending_secure", "session_generations"):
            self.e.d.setdefault(key, {})

    @property
    def d(self):
        return self.e.d

    def emit(self, item, chat="session", mid=None):
        mid = mid or item["body"]["id"]
        self.d["outbox"].append({"item": item, "chat": chat, "mid": mid})
        if "delete_cap" in item["body"]:
            self.d.setdefault("delete_caps", {}).setdefault(
                chat + ":" + mid, []
            ).append({"card": self.e.card, "cap": item["body"]["delete_cap"]})

    def control(self, peer, payload):
        self.emit(
            envelope(
                self.e.identity,
                self.e.peer_card(peer),
                payload,
                int(time.time()) + 7 * 86400,
                "session",
            )
        )

    def ensure(self, peer):
        if peer in self.d["sessions"] or peer in self.d["bootstrap"]:
            return
        if self.e.me < peer:
            secret = ratchet.private_key()
            hello = {
                "action": "hello",
                "sid": uuid.uuid4().hex,
                "initiator": self.e.me,
                "responder": peer,
                "generation": self.d["session_generations"].get(peer, 0),
                "eph": enc(ratchet.public_key(secret)),
            }
            self.d["bootstrap"][peer] = {
                "step": "hello",
                "hello": hello,
                "ephemeral": enc(secret),
                "created": int(time.time()),
            }
            self.control(peer, hello)
        else:
            self.d["bootstrap"][peer] = {"step": "request", "created": int(time.time())}
            self.control(
                peer, {"action": "request", "initiator": peer, "responder": self.e.me}
            )

    def queue(self, peer, payload, expires, kind, chat, mid):
        if peer in self.d["sessions"]:
            self.emit(self.encrypt(peer, payload, expires, kind), chat, mid)
        else:
            pending = self.d["pending_secure"].setdefault(peer, [])
            if len(pending) >= 1000:
                raise ValueError("صف پیام‌های در انتظار پر است")
            pending.append(
                dict(payload=payload, expires=expires, kind=kind, chat=chat, mid=mid)
            )
            self.ensure(peer)

    def flush(self, peer):
        for p in self.d["pending_secure"].pop(peer, []):
            if p["expires"] > time.time():
                self.emit(
                    self.encrypt(peer, p["payload"], p["expires"], p["kind"]),
                    p["chat"],
                    p["mid"],
                )

    def header(self, peer, expires, kind, sid):
        h = {
            "v": 2,
            "id": uuid.uuid4().hex,
            "sender": self.e.me,
            "to": peer,
            "expires": int(expires),
            "kind": kind,
            "sid": sid,
        }
        if kind in ("message", "file", "group", "group_update"):
            h["delete_cap"] = signed(
                self.e.identity,
                dict(
                    context="MehrChat-retract-v2",
                    id=h["id"],
                    sender=self.e.me,
                    to=peer,
                    expires=h["expires"],
                ),
            )
        return h

    def encrypt(self, peer, payload, expires, kind):
        current = self.d["sessions"][peer]
        h = self.header(peer, expires, kind, current["sid"])
        state, packet = ratchet.encrypt(current["state"], pack(payload), pack(h))
        self.d["sessions"][peer] = dict(current, state=state)
        return signed(self.e.identity, dict(h, **packet))

    def receive(self, item, card):
        h = verify(card, item)
        peer = check_card(card)["id"]
        if h["sender"] != peer or h["to"] != self.e.me or h["expires"] <= time.time():
            raise ValueError("Invalid route or expiry")
        if h["v"] == 1:
            if h["kind"] != "session":
                raise ValueError("Legacy content disabled")
            self.bootstrap(peer, open_envelope(self.e.identity, card, item))
            return None
        if h["v"] != 2:
            raise ValueError("Unsupported encryption version")
        if h["kind"] in ("message", "file", "group", "group_update"):
            cap = verify(card, h["delete_cap"])
            if cap != dict(
                context="MehrChat-retract-v2",
                id=h["id"],
                sender=peer,
                to=self.e.me,
                expires=h["expires"],
            ):
                raise ValueError("Invalid retraction proof")
        header = {
            k: h[k] for k in ("v", "id", "sender", "to", "expires", "kind", "sid")
        }
        if "delete_cap" in h:
            header["delete_cap"] = h["delete_cap"]
        ad = pack(header)
        current = self.d["sessions"].get(peer)
        if current is None:
            pending = self.d["bootstrap"].get(peer)
            if (
                not pending
                or pending.get("step") != "ready"
                or pending["sid"] != h["sid"]
                or h["kind"] != "session"
            ):
                raise KeyError("Session not established")
            state, raw = ratchet.initial_receive(
                dec(pending["shared"]), dec(pending["ratchet_private"]), h, ad
            )
            if json.loads(raw) != {
                "action": "ready",
                "sid": h["sid"],
                "transcript": pending["transcript"],
            }:
                raise ValueError("Invalid key confirmation")
            self.d["sessions"][peer] = {
                "sid": h["sid"],
                "state": state,
                "created": int(time.time()),
            }
            del self.d["bootstrap"][peer]
            self.flush(peer)
            return None
        if current["sid"] != h["sid"]:
            raise ValueError("Stale session")
        state, raw = ratchet.decrypt(current["state"], h, ad)
        payload = json.loads(raw)
        if h["kind"] == "session":
            raise ValueError("Unexpected session message")
        self.d["sessions"][peer] = dict(current, state=state)
        return payload

    def discard_session(self, peer):
        self.d["sessions"].pop(peer, None)
        self.d["bootstrap"].pop(peer, None)
        removed = [p for p in self.d["outbox"] if p["item"]["body"]["to"] == peer]
        self.d["outbox"] = [
            p for p in self.d["outbox"] if p["item"]["body"]["to"] != peer
        ]
        pending = self.d["pending_secure"].setdefault(peer, [])
        mids = {p["mid"] for p in pending}
        for p in removed:
            if p["mid"] in mids:
                continue
            message = next(
                (
                    m
                    for m in self.d["messages"].get(p["chat"], [])
                    if m["id"] == p["mid"]
                ),
                None,
            )
            if message and message["expires"] > time.time():
                payload = {
                    k: v for k, v in message.items() if k not in ("state", "deliveries")
                }
                pending.append(
                    dict(
                        payload=payload,
                        expires=payload["expires"],
                        kind=payload["kind"],
                        chat=p["chat"],
                        mid=p["mid"],
                    )
                )
                mids.add(p["mid"])

    def reset(self, peer, minimum=0):
        if self.e.me > peer:
            self.control(
                peer,
                {
                    "action": "reset_request",
                    "generation": self.d["session_generations"].get(peer, 0),
                },
            )
            return
        generation = max(self.d["session_generations"].get(peer, 0), minimum) + 1
        if generation >= 2**31:
            raise ValueError("Generation exhausted")
        self.discard_session(peer)
        self.d["session_generations"][peer] = generation
        self.control(peer, {"action": "reset", "generation": generation})
        self.ensure(peer)

    def bootstrap(self, peer, p):
        fields = {
            'request': {'action', 'initiator', 'responder'},
            'hello': {'action', 'sid', 'initiator', 'responder', 'generation', 'eph'},
            'reply': {'action', 'hello', 'eph', 'ratchet'},
            'generation_hint': {'action', 'generation', 'sid'},
            'reset': {'action', 'generation'},
            'reset_request': {'action', 'generation'},
        }
        if (not isinstance(p, dict) or not isinstance(p.get('action'), str)
                or set(p) != fields.get(p['action']) or len(pack(p)) > 4096):
            raise ValueError('Invalid bootstrap fields')
        action = p.get("action")
        if action == "generation_hint":
            pending = self.d["bootstrap"].get(peer, {})
            g = p.get("generation")
            if self.e.me > peer or type(g) is not int or not 0 <= g < 2**31:
                raise ValueError("Invalid generation hint")
            if (
                pending.get("step") == "hello"
                and pending["hello"]["sid"] == p.get("sid")
                and g > self.d["session_generations"].get(peer, 0)
            ):
                self.reset(peer, g)
            return
        if action in ("reset", "reset_request"):
            g = p.get("generation")
            if type(g) is not int or not 0 <= g < 2**31:
                raise ValueError("Invalid reset")
            if action == "reset_request":
                if self.e.me > peer:
                    raise ValueError("Invalid initiator")
                self.reset(peer, g)
            else:
                if peer > self.e.me:
                    raise ValueError("Invalid initiator")
                if g <= self.d["session_generations"].get(peer, 0):
                    return
                self.discard_session(peer)
                self.d["session_generations"][peer] = g
                self.ensure(peer)
            return
        if action == "request":
            if self.e.me > peer or p != {
                "action": "request",
                "initiator": self.e.me,
                "responder": peer,
            }:
                raise ValueError("Invalid request")
            self.ensure(peer)
            return
        if action == "hello":
            if (
                peer > self.e.me
                or p["initiator"] != peer
                or p["responder"] != self.e.me
            ):
                raise ValueError("Invalid initiator")
            g = p.get("generation")
            expected = self.d["session_generations"].get(peer, 0)
            if type(g) is not int or not 0 <= g < 2**31:
                raise ValueError("Invalid generation")
            if g < expected:
                self.control(
                    peer,
                    {
                        "action": "generation_hint",
                        "generation": expected,
                        "sid": p["sid"],
                    },
                )
                return
            if g > expected:
                raise KeyError("Waiting for reset")
            if len(dec(p["eph"])) != 32 or len(p["sid"]) != 32:
                raise ValueError("Invalid ephemeral key")
            if peer in self.d["sessions"]:
                return
            existing = self.d["bootstrap"].get(peer, {})
            if existing.get("step") == "ready":
                if existing["sid"] == p["sid"]:
                    self.control(peer, existing["reply"])
                    return
                raise ValueError("Bootstrap in progress")
            ephemeral, private = ratchet.private_key(), ratchet.private_key()
            reply = {
                "action": "reply",
                "hello": p,
                "eph": enc(ratchet.public_key(ephemeral)),
                "ratchet": enc(ratchet.public_key(private)),
            }
            transcript = {"hello": p, "reply": reply}
            shared = ratchet.agree(ephemeral, dec(p["eph"]), transcript)
            self.d["bootstrap"][peer] = dict(
                step="ready",
                sid=p["sid"],
                shared=enc(shared),
                ratchet_private=enc(private),
                transcript=hashlib.sha256(pack(transcript)).hexdigest(),
                created=int(time.time()),
                reply=reply,
            )
            self.control(peer, reply)
            return
        if action == "reply":
            pending = self.d["bootstrap"].get(peer)
            if (
                not pending
                or pending["step"] != "hello"
                or p["hello"] != pending["hello"]
            ):
                raise ValueError("Unmatched reply")
            transcript = {"hello": pending["hello"], "reply": p}
            shared = ratchet.agree(dec(pending["ephemeral"]), dec(p["eph"]), transcript)
            sid = pending["hello"]["sid"]
            h = self.header(peer, int(time.time()) + 7 * 86400, "session", sid)
            ready = {
                "action": "ready",
                "sid": sid,
                "transcript": hashlib.sha256(pack(transcript)).hexdigest(),
            }
            state, packet = ratchet.initial_send(
                shared, dec(p["ratchet"]), pack(ready), pack(h)
            )
            self.d["sessions"][peer] = dict(
                sid=sid, state=state, created=int(time.time())
            )
            del self.d["bootstrap"][peer]
            self.emit(signed(self.e.identity, dict(h, **packet)))
            self.flush(peer)
            return
        raise ValueError("Invalid bootstrap action")
