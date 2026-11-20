from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_VERSION = 1  # ponytail: single master key; add a {version: key} map when rotating


def _key() -> bytes:
    try:
        key = base64.b64decode(os.environ.get("VAULT_MASTER_KEY", ""), validate=True)
    except ValueError:  # binascii.Error subclasses ValueError
        key = b""
    if len(key) != 32:
        raise RuntimeError("VAULT_MASTER_KEY must be base64 of 32 random bytes")
    return key


def encrypt(plaintext: str, aad: str) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    return nonce, AESGCM(_key()).encrypt(nonce, plaintext.encode(), aad.encode())


def decrypt(nonce: bytes, ciphertext: bytes, aad: str) -> str:
    return AESGCM(_key()).decrypt(bytes(nonce), bytes(ciphertext), aad.encode()).decode()
