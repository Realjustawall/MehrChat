"""Owner-signed membership chains; group-scoped cards do not verify private contacts."""

import hashlib, secrets, unicodedata
from .crypto import signed, verify, check_card, pack


class Groups:
    def __init__(self, engine):
        self.e = engine

    def make(self, name, members, chat=None):
        if not isinstance(members, list) or not all(isinstance(p, str) for p in members):
            raise ValueError("Invalid membership")
        roster = sorted(set(members + [self.e.me]))
        old = self.e.d["groups"].get(chat) if chat else None
        if old and old["body"]["owner"] != self.e.me:
            raise ValueError("فقط سازنده گروه می‌تواند اعضا را تغییر دهد")
        chain = list(old.get("chain", [])) if old else []
        body = {
            "v": 2,
            "id": chat or secrets.token_hex(32),
            "epoch": len(chain),
            "owner": self.e.me,
            "name": name,
            "members": roster,
            "cards": {p: self.e.peer_card(p) for p in roster},
            "previous": hashlib.sha256(pack(chain[-1])).hexdigest() if chain else None,
        }
        chain.append(signed(self.e.identity, body))
        descriptor = {"body": body, "chain": chain}
        self.validate(descriptor, self.e.me)
        return descriptor

    def require_verified(self, descriptor):
        # Owner signatures authenticate the roster, not independent ownership
        # of every participant's device. Never auto-trust group-scoped cards.
        if "private" not in descriptor and any(
            p != self.e.me and p not in self.e.d["contacts"]
            for p in descriptor["body"]["members"]
        ):
            raise ValueError("پیش از ارسال، اثر انگشت همه اعضای گروه را تأیید کنید")

    def safety_code(self, descriptor):
        return hashlib.sha256(b"MehrChat-group-safety-v1\0" + pack(descriptor)).hexdigest()

    def validate(self, descriptor, sender, allow_removed=False):
        if not isinstance(descriptor, dict):
            raise ValueError("Invalid group descriptor")
        if "private" in descriptor:
            members = descriptor["private"]
            if (
                len(members) != 2
                or len(set(members)) != 2
                or self.e.me not in members
                or sender not in members
            ):
                raise ValueError("Invalid private chat")
            for p in members:
                if p != self.e.me and p not in self.e.d["contacts"]:
                    raise KeyError("Private contact not verified")
                check_card(self.e.peer_card(p))
            return hashlib.sha256(pack(sorted(members))).hexdigest(), members, False
        body = descriptor["body"]
        owner = body["owner"]
        if "chain" not in descriptor:
            # Old unversioned descriptors cannot silently downgrade membership
            # history validation. Existing local history remains readable.
            raise ValueError("Unsigned membership history is not supported")
        else:
            chain = descriptor["chain"]
            if not 1 <= len(chain) <= 64 or chain[-1]["body"] != body:
                raise ValueError("Invalid group chain")
            gid = body["id"]
            if not isinstance(gid, str) or len(gid) != 64 or any(c not in "0123456789abcdef" for c in gid):
                raise ValueError("Invalid group ID")
            if (
                gid not in self.e.d["groups"]
                and owner != self.e.me
                and owner not in self.e.d["contacts"]
            ):
                raise KeyError("Group creator is not verified")
            owner_card = self.e.peer_card(owner)
            for i, entry in enumerate(chain):
                b = verify(owner_card, entry)
                members = b["members"]
                expected = hashlib.sha256(pack(chain[i - 1])).hexdigest() if i else None
                if (
                    type(b["v"]) is not int or b["v"] != 2
                    or b["id"] != gid
                    or b["owner"] != owner
                    or type(b["epoch"]) is not int or b["epoch"] != i
                    or b["previous"] != expected
                ):
                    raise ValueError("Invalid group epoch")
                if (
                    not isinstance(members, list)
                    or not all(isinstance(p, str) and len(p) == 64 for p in members)
                    or not 2 <= len(members) <= 32
                    or len(set(members)) != len(members)
                    or owner not in members
                ):
                    raise ValueError("Invalid membership")
                if set(b["cards"]) != set(members):
                    raise ValueError("Invalid cards")
                for p, card in b["cards"].items():
                    if check_card(card)["id"] != p:
                        raise ValueError("Invalid group card")
                    if (
                        p in self.e.d["contacts"]
                        and self.e.d["contacts"][p]["body"]["id"] != p
                    ):
                        raise ValueError("Conflicting identity")
                if (not isinstance(b["name"], str) or not 1 <= len(b["name"].strip()) <= 80
                    or any(unicodedata.category(c) in ("Cc", "Cs") or c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for c in b["name"])):
                    raise ValueError("Invalid group name")
            old = self.e.d["groups"].get(gid)
            if old and "chain" in old:
                if (
                    len(chain) < len(old["chain"])
                    or chain[: len(old["chain"])] != old["chain"]
                ):
                    raise ValueError("Stale or forked group")
        members = body["members"]
        if (
            not 2 <= len(members) <= 32
            or len(set(members)) != len(members)
            or not 1 <= len(body["name"]) <= 80
        ):
            raise ValueError("Invalid group")
        if sender not in members or owner not in members:
            raise ValueError("Not a member")
        if self.e.me not in members and not (
            allow_removed and gid in self.e.d["groups"]
        ):
            raise ValueError("Not a member")
        return gid, members, True
