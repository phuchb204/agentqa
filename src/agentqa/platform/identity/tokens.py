from __future__ import annotations

import secrets
from hashlib import sha256

TOKEN_BYTES = 32
NONCE_BYTES = 24


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def generate_nonce() -> str:
    return secrets.token_urlsafe(NONCE_BYTES)


def hash_token(raw_token: str) -> str:
    return sha256(raw_token.encode("utf-8")).hexdigest()
