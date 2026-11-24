"""Per-case envelope encryption. A data key is wrapped by MASTER_KEY. Destroying the wrapper makes payloads unreadable."""

from __future__ import annotations

import contextvars
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator

from app.core.errors import AppError

data_key_context: contextvars.ContextVar[bytes | None] = contextvars.ContextVar("data_key", default=None)


class TamperError(AppError):
    def __init__(self) -> None:
        super().__init__("tamper", "Ciphertext failed authentication", status_code=400)


class KeyDestroyed(AppError):
    def __init__(self) -> None:
        super().__init__("key_destroyed", "Case key has been destroyed", status_code=410)


def generate_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encode_master_key(raw: bytes) -> str:
    if len(raw) != 32:
        raise ValueError("master key must be 32 bytes")
    return urlsafe_b64encode(raw).decode("ascii")


def decode_master_key(encoded: str) -> bytes:
    if not encoded:
        raise ValueError("MASTER_KEY is not set")
    raw = urlsafe_b64decode(encoded.encode("ascii"))
    if len(raw) != 32:
        raise ValueError("MASTER_KEY must decode to 32 bytes")
    return raw


def seal(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return b"\x01" + nonce + ciphertext


def open_seal(blob: bytes, key: bytes) -> bytes:
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 1 + 12 + 16 or blob[0] != 1:
        raise TamperError()
    try:
        return AESGCM(key).decrypt(bytes(blob[1:13]), bytes(blob[13:]), None)
    except InvalidTag as exc:
        raise TamperError() from exc


def wrap_data_key(data_key: bytes, master_key: bytes) -> bytes:
    return seal(data_key, master_key)


def unwrap_data_key(wrapped: bytes | None, master_key: bytes) -> bytes:
    if not wrapped:
        raise KeyDestroyed()
    return open_seal(wrapped, master_key)


def seal_text(text: str, key: bytes) -> bytes:
    return seal(text.encode("utf-8"), key)


def open_text(blob: bytes, key: bytes) -> str:
    return open_seal(blob, key).decode("utf-8")


class EncryptedText(TypeDecorator):
    """Stores a string as AES-GCM bytes. The active case key comes from data_key_context."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        key = data_key_context.get()
        if key is None:
            raise KeyDestroyed()
        raw = value.encode("utf-8") if isinstance(value, str) else value
        return seal(raw, key)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        key = data_key_context.get()
        if key is None:
            raise KeyDestroyed()
        return open_seal(value, key).decode("utf-8")
