"""Owner-signed membership chains; group-scoped cards do not verify private contacts."""

import hashlib, secrets
from .crypto import signed, verify, check_card, pack


class Groups:
    def __init__(self, engine):
        self.e = engine

    def make(self, name, members, chat=None):
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

    def validate(self, descriptor, sender, allow_removed=False):
        if not isinstance(descriptor, dict):
            raise ValueError('Invalid chat descriptor')
        if "private" in descriptor:
            if set(descriptor) != {'private'}:
                raise ValueError('Invalid private chat fields')
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
        if set(descriptor) not in ({'body', 'sig'}, {'body', 'chain'}):
            raise ValueError('Invalid group descriptor fields')
        owner = body["owner"]
        if "chain" not in descriptor:
            # Legacy descriptors predate epoch chains. Bound their entire
            # representation before retaining them in history/group state.
            if len(pack(descriptor)) > 16384:
                raise ValueError('Legacy group descriptor too large')
            verify(self.e.peer_card(owner), descriptor)
            for p in body["members"]:
                check_card(self.e.peer_card(p))
            gid = hashlib.sha256(pack(descriptor)).hexdigest()
        else:
            chain = descriptor["chain"]
            if not 1 <= len(chain) <= 64 or chain[-1]["body"] != body:
                raise ValueError("Invalid group chain")
            gid = body["id"]
            if len(gid) != 64 or any(c not in "0123456789abcdef" for c in gid):
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
                if set(entry) != {'body', 'sig'} or set(b) != {'v', 'id', 'epoch', 'owner', 'name', 'members', 'cards', 'previous'}:
                    raise ValueError('Invalid group epoch fields')
                members = b["members"]
                expected = hashlib.sha256(pack(chain[i - 1])).hexdigest() if i else None
                if (
                    b["v"] != 2
                    or b["id"] != gid
                    or b["owner"] != owner
                    or b["epoch"] != i
                    or b["previous"] != expected
                ):
                    raise ValueError("Invalid group epoch")
                if (
                    not 2 <= len(members) <= 32
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
                if not 1 <= len(b["name"]) <= 80:
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
