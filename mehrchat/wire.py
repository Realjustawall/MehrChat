"""Pinned Noise NK over TCP or verified TLS; never downgrade on failure."""

import asyncio, json, struct
from noise.connection import NoiseConnection, Keypair
from .crypto import pack, enc, dec, signed, verify

MAX_FRAME = 16 * 1024 * 1024
NOISE_MAX = 65535
RECORD_TIMEOUT = 60
CHUNK_SIZE = 60000


class ReceiveBudget:
    """Shared by relay channels; reserve declared sizes before allocation."""
    def __init__(self, maximum=32 * 1024 * 1024):
        self.maximum, self.used = maximum, 0

    def reserve(self, size):
        if self.used + size > self.maximum:
            raise ValueError("Relay receive budget exhausted")
        self.used += size

    def release(self, size):
        self.used -= size


async def read_frame(reader, maximum=MAX_FRAME):
    size = struct.unpack("!I", await asyncio.wait_for(reader.readexactly(4), 45))[0]
    if not 1 <= size <= maximum:
        raise ValueError("Frame too large")
    return await asyncio.wait_for(reader.readexactly(size), 45)


async def write_frame(writer, data, maximum=MAX_FRAME):
    if not 1 <= len(data) <= maximum:
        raise ValueError("Frame too large")
    writer.write(struct.pack("!I", len(data)) + data)
    await asyncio.wait_for(writer.drain(), 15)


class Channel:
    def __init__(self, reader, writer, noise, budget=None):
        self.reader, self.writer, self.noise = reader, writer, noise
        self.budget = budget

    async def send(self, payload):
        raw = pack(payload)
        if len(raw) > MAX_FRAME:
            raise ValueError("Record too large")
        await write_frame(
            self.writer, self.noise.encrypt(struct.pack("!I", len(raw))), NOISE_MAX
        )
        for start in range(0, len(raw), 60000):
            await write_frame(
                self.writer, self.noise.encrypt(raw[start : start + 60000]), NOISE_MAX
            )

    async def recv(self, maximum=MAX_FRAME):
        return await asyncio.wait_for(self._recv(maximum), RECORD_TIMEOUT)

    async def _recv(self, maximum):
        length = self.noise.decrypt(await read_frame(self.reader, NOISE_MAX))
        if len(length) != 4:
            raise ValueError("Invalid encrypted length")
        size = struct.unpack("!I", length)[0]
        if not 1 <= size <= min(maximum, MAX_FRAME):
            raise ValueError("Record too large")
        if self.budget:
            self.budget.reserve(size)
        try:
            raw = bytearray()
            while len(raw) < size:
                part = self.noise.decrypt(await read_frame(self.reader, NOISE_MAX))
                if len(part) != min(CHUNK_SIZE, size - len(raw)):
                    raise ValueError("Invalid segmentation")
                raw.extend(part)
            return json.loads(raw)
        finally:
            if self.budget:
                self.budget.release(size)

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (OSError, ConnectionError):
            pass


async def initiate(reader, writer, pin):
    noise = NoiseConnection.from_name(b"Noise_NK_25519_ChaChaPoly_SHA256")
    noise.set_as_initiator()
    noise.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC, dec(pin))
    noise.start_handshake()
    await write_frame(writer, noise.write_message(), NOISE_MAX)
    noise.read_message(await read_frame(reader, NOISE_MAX))
    return Channel(reader, writer, noise)


async def connect(host, port, pin, identity, card, *, transport="noise", ca=""):
    from .connection import open_transport
    reader, writer = await open_transport(dict(host=host, port=port, transport=transport, ca=ca))
    try:
        channel = await initiate(reader, writer, pin)
        noise = channel.noise
        await channel.send(
            {
                "card": card,
                "proof": signed(
                    identity,
                    {
                        "context": "MehrChat-login-v2",
                        "transcript": enc(noise.get_handshake_hash()),
                    },
                ),
            }
        )
        result = await channel.recv()
        if not result.get("ok"):
            raise ValueError(result.get("error", "Authentication failed"))
        return channel
    except BaseException:
        writer.close()
        raise


async def accept(reader, writer, identity, register=None, budget=None):
    noise = NoiseConnection.from_name(b"Noise_NK_25519_ChaChaPoly_SHA256")
    noise.set_as_responder()
    noise.set_keypair_from_private_bytes(Keypair.STATIC, dec(identity["box_secret"]))
    noise.start_handshake()
    noise.read_message(await read_frame(reader, NOISE_MAX))
    await write_frame(writer, noise.write_message(), NOISE_MAX)
    channel = Channel(reader, writer, noise, budget)
    auth = await channel.recv(maximum=4096)
    if auth == {"op": "probe"}:
        from .connection import PROTOCOL
        from . import __version__
        await channel.send({"ok": True, "protocol": PROTOCOL, "version": __version__})
        return channel, None
    if not isinstance(auth, dict) or set(auth) != {'card', 'proof'}:
        raise ValueError('Invalid authentication fields')
    if verify(auth["card"], auth["proof"]) != {
        "context": "MehrChat-login-v2",
        "transcript": enc(noise.get_handshake_hash()),
    }:
        raise ValueError("Invalid proof")
    if register:
        try:
            register(auth["card"])
        except ValueError as exc:
            await channel.send({"ok": False, "error": str(exc)})
            raise
    await channel.send({"ok": True})
    return channel, auth["card"]
