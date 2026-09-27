"""Password hashing and session tokens.

Uses stdlib pbkdf2_hmac so we don't take on passlib/bcrypt just for a demo.
Hashes are self-describing: algo$iterations$salt$hexdigest, so rotating the
algorithm later doesn't invalidate existing rows.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlmodel import Session, select

from ..models import StoreUser

ITERATIONS = 200_000
ALGO = "pbkdf2_sha256"
SESSION_TTL = timedelta(days=7)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), ITERATIONS
    )
    return f"{ALGO}${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, expected = stored.split("$")
        iterations = int(iterations)
    except ValueError:
        return False
    if algo != ALGO:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), iterations
    )
    return secrets.compare_digest(digest.hex(), expected)


def authenticate(
    session: Session, username: str, password: str
) -> StoreUser | None:
    user = session.exec(
        select(StoreUser).where(StoreUser.username == username)
    ).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user