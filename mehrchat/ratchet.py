"""Double Ratchet library integration; independent protocol audit still required."""

import asyncio, hashlib
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.exceptions import InvalidTag
from doubleratchet import DoubleRatchet, Header, EncryptedMessage
from doubleratchet.aead import AEAD, AuthenticationFailedException
from doubleratchet.recommended.diffie_hellman_ratchet_curve25519 import (
    DiffieHellmanRatchet,
)
from doubleratchet.recommended.kdf_hkdf import KDF as Root
from doubleratchet.recommended.kdf_separate_hmacs import KDF as Chain
from doubleratchet.recommended.crypto_provider import HashFunction
from nacl.utils import random
from .crypto import pack, enc, dec


class RootKDF(Root):
    @staticmethod
    def _get_hash_function():
        return HashFunction.SHA_256

    @staticmethod
    def _get_info():
        return b"MehrChat-v2-DR-root"


class ChainKDF(Chain):
    @staticmethod
    def _get_hash_function():
        return HashFunction.SHA_256


class Cipher(AEAD):
    @staticmethod
    async def encrypt(plaintext, key, associated_data):
        nonce = random(12)
        return nonce + ChaCha20Poly1305(key).encrypt(nonce, plaintext, associated_data)

    @staticmethod
    async def decrypt(ciphertext, key, associated_data):
        try:
            return ChaCha20Poly1305(key).decrypt(
                ciphertext[:12], ciphertext[12:], associated_data
            )
        except (InvalidTag, ValueError) as exc:
            raise AuthenticationFailedException("Authentication failed") from exc


class Ratchet(DoubleRatchet):
    @staticmethod
    def _build_associated_data(ad, header):
        return pack({"context": enc(ad), "header": encode_header(header)})


OPTIONS = dict(
    diffie_hellman_ratchet_class=DiffieHellmanRatchet,
    root_chain_kdf=RootKDF,
    message_chain_kdf=ChainKDF,
    message_chain_constant=b"\x01\x02",
    dos_protection_threshold=1000,
    max_num_skipped_message_keys=1000,
    aead=Cipher,
)


def encode_header(h):
    return {
        "dh": enc(h.ratchet_pub),
        "pn": h.previous_sending_chain_length,
        "n": h.sending_chain_length,
    }


def decode_message(p):
    h = p["ratchet"]
    if (
        not all(type(h[k]) is int and 0 <= h[k] < 2**31 for k in ("pn", "n"))
        or len(dec(h["dh"])) != 32
    ):
        raise ValueError("Invalid ratchet header")
    return EncryptedMessage(Header(dec(h["dh"]), h["pn"], h["n"]), dec(p["ciphertext"]))


def private_key():
    return X25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )


def public_key(s):
    return (
        X25519PrivateKey.from_private_bytes(s)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def agree(s, p, transcript):
    secret = X25519PrivateKey.from_private_bytes(s).exchange(
        X25519PublicKey.from_public_bytes(p)
    )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=hashlib.sha256(pack(transcript)).digest(),
        info=b"MehrChat-v2-interactive-session",
    ).derive(secret)


_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="MehrCrypto")


def run(factory):
    return _POOL.submit(lambda: asyncio.run(factory())).result()


def initial_send(secret, public, plaintext, ad):
    async def operation():
        state, msg = await Ratchet.encrypt_initial_message(
            **OPTIONS,
            shared_secret=secret,
            recipient_ratchet_pub=public,
            message=plaintext,
            associated_data=ad
        )
        return state.json, {
            "ratchet": encode_header(msg.header),
            "ciphertext": enc(msg.ciphertext),
        }

    return run(operation)


def initial_receive(secret, private, p, ad):
    async def operation():
        state, plain = await Ratchet.decrypt_initial_message(
            **OPTIONS,
            shared_secret=secret,
            own_ratchet_priv=private,
            message=decode_message(p),
            associated_data=ad
        )
        return state.json, plain

    return run(operation)


def encrypt(state, plain, ad):
    async def operation():
        current = Ratchet.from_json(state, **OPTIONS)
        msg = await current.encrypt_message(plain, ad)
        return current.json, {
            "ratchet": encode_header(msg.header),
            "ciphertext": enc(msg.ciphertext),
        }

    return run(operation)


def decrypt(state, p, ad):
    async def operation():
        current = Ratchet.from_json(state, **OPTIONS)
        plain = await current.decrypt_message(decode_message(p), ad)
        return current.json, plain

    return run(operation)
