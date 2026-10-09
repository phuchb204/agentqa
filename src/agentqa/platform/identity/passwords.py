from __future__ import annotations

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()


def hash_password(raw_password: str) -> str:
    return _hasher.hash(raw_password)


def verify_password(raw_password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        return _hasher.verify(raw_password, stored_hash)
    except Exception:
        return False


def password_hash_needs_update(stored_hash: str) -> bool:
    return _hasher.needs_update(stored_hash)
