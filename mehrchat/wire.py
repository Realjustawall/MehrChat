"""Pinned Noise NK over outbound TCP. No TLS or unauthenticated fallback."""

import asyncio, ipaddress, json, struct
import re
from noise.connection import NoiseConnection, Keypair
from .crypto import pack, enc, dec, signed, verify

MAX_FRAME = 16 * 1024 * 1024
NOISE_MAX = 65535
RECORD_TIMEOUT = 120


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
    def __init__(self, reader, writer, noise):
        self.reader, self.writer, self.noise = reader, writer, noise

    async def send(self, payload):
        raw = pack(payload)
        if len(raw) > MAX_FRAME:
            raise ValueError("Record too large")
        # JSON permits trailing whitespace. Pad inside the authenticated Noise
        # record without changing the application schema or legacy decoder.
        raw += b" " * (-len(raw) % 1024)
        await write_frame(
            self.writer, self.noise.encrypt(struct.pack("!I", len(raw))), NOISE_MAX
        )
        for start in range(0, len(raw), 60000):
            await write_frame(
                self.writer, self.noise.encrypt(raw[start : start + 60000]), NOISE_MAX
            )

    async def recv(self):
        # A peer cannot keep a segmented record alive indefinitely by trickling
        # another frame just before each individual frame deadline.
        return await asyncio.wait_for(self._recv(), RECORD_TIMEOUT)

    async def _recv(self):
        length = self.noise.decrypt(await read_frame(self.reader, NOISE_MAX))
        if len(length) != 4:
            raise ValueError("Invalid encrypted length")
        size = struct.unpack("!I", length)[0]
        if not 1 <= size <= MAX_FRAME:
            raise ValueError("Record too large")
        raw = bytearray()
        while len(raw) < size:
            part = self.noise.decrypt(await read_frame(self.reader, NOISE_MAX))
            if not part or len(raw) + len(part) > size:
                raise ValueError("Invalid segmentation")
            raw.extend(part)
        return json.loads(raw)

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (OSError, ConnectionError):
            pass


def validate_proxy(proxy):
    """Only a device-local proxy: never resolve the destination through local DNS."""
    if proxy is None:
        return None
    if not isinstance(proxy, dict) or set(proxy) != {"host", "port"}:
        raise ValueError("پراکسی محلی معتبر نیست")
    try:
        address = ipaddress.ip_address(proxy["host"])
    except (ValueError, TypeError):
        raise ValueError("پراکسی محلی معتبر نیست") from None
    if not address.is_loopback or type(proxy["port"]) is not int or not 1 <= proxy["port"] <= 65535:
        raise ValueError("پراکسی محلی معتبر نیست")
    return {"host": str(address), "port": proxy["port"]}


def validate_destination(host, port):
    if not isinstance(host, str) or not host or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("مشخصات سرور معتبر نیست")
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    try:
        domain = host.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError:
        raise ValueError("مشخصات سرور معتبر نیست") from None
    if len(domain) > 253 or not all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in domain.split(".")
    ):
        raise ValueError("مشخصات سرور معتبر نیست")


async def open_transport(host, port, proxy=None):
    validate_destination(host, port)
    proxy = validate_proxy(proxy)
    if proxy is None:
        if host.lower().rstrip(".").endswith(".onion"):
            raise ValueError("اتصال onion به پراکسی نیاز دارد")
        return await asyncio.open_connection(host, port)
    reader, writer = await asyncio.open_connection(proxy["host"], proxy["port"])
    try:
        # RFC 1928 CONNECT. Destination DNS is resolved by the proxy, including onion names.
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        if await reader.readexactly(2) != b"\x05\x00":
            raise ValueError("اتصال پراکسی برقرار نشد")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            encoded = host.encode("idna")
            if not 1 <= len(encoded) <= 255 or any(c < 33 or c == 127 for c in encoded):
                raise ValueError("مشخصات سرور معتبر نیست")
            destination = b"\x03" + bytes([len(encoded)]) + encoded
        else:
            destination = (b"\x01" if address.version == 4 else b"\x04") + address.packed
        writer.write(b"\x05\x01\x00" + destination + struct.pack("!H", port))
        await writer.drain()
        version, reply, reserved, kind = await reader.readexactly(4)
        if version != 5 or reply != 0 or reserved != 0:
            raise ValueError("اتصال پراکسی برقرار نشد")
        if kind == 1:
            size = 4
        elif kind == 4:
            size = 16
        elif kind == 3:
            size = (await reader.readexactly(1))[0]
            if size == 0:
                raise ValueError("اتصال پراکسی برقرار نشد")
        else:
            raise ValueError("اتصال پراکسی برقرار نشد")
        await reader.readexactly(size + 2)
        return reader, writer
    except BaseException:
        writer.close()
        raise


async def connect(host, port, pin, identity, card, proxy=None):
    reader, writer = await asyncio.wait_for(open_transport(host, port, proxy), 30 if proxy else 12)
    try:
        noise = NoiseConnection.from_name(b"Noise_NK_25519_ChaChaPoly_SHA256")
        noise.set_as_initiator()
        noise.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC, dec(pin))
        noise.start_handshake()
        await write_frame(writer, noise.write_message(), NOISE_MAX)
        noise.read_message(await read_frame(reader, NOISE_MAX))
        channel = Channel(reader, writer, noise)
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


async def accept(reader, writer, identity, register=None):
    noise = NoiseConnection.from_name(b"Noise_NK_25519_ChaChaPoly_SHA256")
    noise.set_as_responder()
    noise.set_keypair_from_private_bytes(Keypair.STATIC, dec(identity["box_secret"]))
    noise.start_handshake()
    noise.read_message(await read_frame(reader, NOISE_MAX))
    await write_frame(writer, noise.write_message(), NOISE_MAX)
    channel = Channel(reader, writer, noise)
    auth = await channel.recv()
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
