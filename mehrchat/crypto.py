"""Experimental composition of libsodium primitives. NOT Signal / MLS."""

import base64
import hashlib
import json
import re
import time
import uuid
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey, VerifyKey
from nacl.secret import SecretBox
from nacl.pwhash import argon2id
from nacl.utils import random


def pack(obj):
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def enc(raw):
    return base64.b64encode(bytes(raw)).decode("ascii")


def dec(s):
    return base64.b64decode(s, validate=True)


def uid(sign, box):
    return hashlib.sha256(b"MehrChat identity v1\0" + dec(sign) + dec(box)).hexdigest()


def create_identity(username, name):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", username):
        raise ValueError("نام کاربری: ۴ تا ۳۲ حرف انگلیسی، عدد یا زیرخط")
    if not 1 <= len(name) <= 80:
        raise ValueError("نام نمایشی نامعتبر است")
    sk, bk = SigningKey.generate(), PrivateKey.generate()
    return {
        "sign_secret": enc(sk),
        "box_secret": enc(bk),
        "username": username,
        "name": name,
    }


def public_card(identity):
    body = {
        "v": 1,
        "sign": enc(SigningKey(dec(identity["sign_secret"])).verify_key),
        "box": enc(PrivateKey(dec(identity["box_secret"])).public_key),
        "username": identity["username"],
        "name": identity["name"],
    }
    body["id"] = uid(body["sign"], body["box"])
    return {
        "body": body,
        "sig": enc(SigningKey(dec(identity["sign_secret"])).sign(pack(body)).signature),
    }


def check_card(card):
    # Cards are signed public identities, not arbitrary signed storage records.
    if not isinstance(card, dict) or set(card) != {"body", "sig"}:
        raise ValueError("Invalid identity card fields")
    if not isinstance(card["sig"], str) or len(card["sig"]) != 88:
        raise ValueError("Invalid identity signature")
    b = card["body"]
    if (not isinstance(b, dict)
            or set(b) != {"v", "sign", "box", "username", "name", "id"}
            or type(b["v"]) is not int
            or any(not isinstance(b[k], str) for k in ("sign", "box", "username", "name", "id"))
            or len(b["sign"]) != 44 or len(b["box"]) != 44
            or len(b["id"]) != 64 or len(b["username"]) > 32 or len(b["name"]) > 80):
        raise ValueError("Invalid identity card fields")
    if b["v"] != 1 or b["id"] != uid(b["sign"], b["box"]):
        raise ValueError("Invalid identity")
    if len(dec(b["sign"])) != 32 or len(dec(b["box"])) != 32:
        raise ValueError("Invalid key")
    VerifyKey(dec(b["sign"])).verify(pack(b), dec(card["sig"]))
    if (
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", b["username"])
        or not 1 <= len(b["name"]) <= 80
    ):
        raise ValueError("Invalid profile")
    return b


def signed(identity, obj):
    return {
        "body": obj,
        "sig": enc(SigningKey(dec(identity["sign_secret"])).sign(pack(obj)).signature),
    }


def verify(card, obj):
    if (not isinstance(obj, dict) or set(obj) != {'body', 'sig'}
            or not isinstance(obj['body'], dict) or not isinstance(obj['sig'], str)
            or len(obj['sig']) != 88):
        raise ValueError('Invalid signed object fields')
    b = check_card(card)
    VerifyKey(dec(b["sign"])).verify(pack(obj["body"]), dec(obj["sig"]))
    return obj["body"]


def envelope(identity, recipient, payload, expires, kind="message"):
    rb = check_card(recipient)
    sender = public_card(identity)["body"]["id"]
    header = {
        "v": 1,
        "id": uuid.uuid4().hex,
        "sender": sender,
        "to": rb["id"],
        "expires": int(expires),
        "kind": kind,
    }
    plain = {"header": header, "payload": payload}
    ciphertext = enc(SealedBox(PublicKey(dec(rb["box"]))).encrypt(pack(plain)))
    return signed(identity, dict(header, ciphertext=ciphertext))


def open_envelope(identity, sender_card, item, now=None):
    h = verify(sender_card, item)
    if h["v"] != 1 or h["sender"] != check_card(sender_card)["id"]:
        raise ValueError("Invalid sender")
    if h["to"] != public_card(identity)["body"]["id"]:
        raise ValueError("Wrong recipient")
    if h["expires"] <= (time.time() if now is None else now):
        raise ValueError("Expired")
    raw = SealedBox(PrivateKey(dec(identity["box_secret"]))).decrypt(
        dec(h["ciphertext"])
    )
    obj = json.loads(raw)
    if obj["header"] != {k: v for k, v in h.items() if k != "ciphertext"}:
        raise ValueError("Header mismatch")
    return obj["payload"]


def derive(password, salt):
    if len(password) < 12:
        raise ValueError("رمز باید حداقل ۱۲ نویسه باشد")
    return argon2id.kdf(
        SecretBox.KEY_SIZE,
        password.encode(),
        salt,
        opslimit=argon2id.OPSLIMIT_MODERATE,
        memlimit=argon2id.MEMLIMIT_MODERATE,
    )
