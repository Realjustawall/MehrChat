"""Validated public routing profiles and authenticated pre-login probes."""
import asyncio
import json
import ssl
import certifi
from .crypto import dec

PROTOCOL = "Noise_NK_25519_ChaChaPoly_SHA256"


def validate_profile(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid server profile")
    host = value.get("host", "").strip()
    port = int(value.get("port", 8787))
    pin = value.get("pin", "")
    transport = value.get("transport", "noise")
    ca = value.get("ca", "")
    if (not host or len(host) > 253 or any(c.isspace() or c in '/\\\x00' for c in host)
            or not 1 <= port <= 65535 or len(dec(pin)) != 32
            or transport not in ("noise", "tls") or not isinstance(ca, str)
            or len(ca) > 32768 or "PRIVATE KEY" in ca):
        raise ValueError("Invalid server profile")
    if transport == "tls":
        tls_context(ca)
    return dict(host=host, port=port, pin=pin, transport=transport, ca=ca)


def tls_context(ca=""):
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=certifi.where())
    if ca:
        context.load_verify_locations(cadata=ca)
    return context


async def open_transport(profile, *, connect_host=None):
    options = {}
    if profile.get("transport", "noise") == "tls":
        options = dict(ssl=tls_context(profile.get("ca", "")), server_hostname=profile["host"],
                       ssl_handshake_timeout=12)
    return await asyncio.wait_for(asyncio.open_connection(connect_host or profile["host"], int(profile["port"]), **options), 15)


async def probe(profile, *, connect_host=None):
    from .wire import initiate
    profile = validate_profile(profile)
    channel = None
    writer = None
    try:
        reader, writer = await open_transport(profile, connect_host=connect_host)
        channel = await initiate(reader, writer, profile["pin"])
        await channel.send({"op": "probe"})
        result = await channel.recv()
        if result.get("protocol") != PROTOCOL or result.get("ok") is not True:
            raise ValueError("Incompatible relay")
        return result
    finally:
        if channel:
            await channel.close()
        elif writer:
            writer.close()


def bundled_profile():
    try:
        from ._deployment import PROFILE
    except ImportError:
        return None
    return validate_profile(PROFILE)
