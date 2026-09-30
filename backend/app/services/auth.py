"""Password hashing and session tokens.

Uses stdlib pbkdf2_hmac so we don't take on passlib/bcrypt just for a demo.
Hashes are self-describing: algo$iterations$salt$hexdigest, so rotating the
algorithm later doesn't invalidate existing rows.

Bearer tokens are random and handed to the browser once; the database keeps
only their SHA-256, the same way it keeps only a hash of the password.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from ..models import AuthSession, Store, StoreUser, utc_now

ITERATIONS = 200_000
ALGO = "pbkdf2_sha256"
SESSION_TTL = timedelta(days=7)
MIN_PASSWORD_LENGTH = 8

# Checked against when the username does not exist, so a wrong username takes
# as long to reject as a wrong password and cannot be told apart by timing.
_DUMMY_HASH = f"{ALGO}${ITERATIONS}${'0' * 32}${'0' * 64}"


def normalise_username(username: str) -> str:
    return username.strip().lower()


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
        select(StoreUser).where(StoreUser.username == normalise_username(username))
    ).first()
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(session: Session, user: StoreUser) -> tuple[str, AuthSession]:
    """Start a session for ``user``. Returns the raw token -- the only copy."""
    token = secrets.token_urlsafe(32)
    now = utc_now()
    row = AuthSession(
        token_hash=_token_hash(token),
        store_id=user.store_id,
        user_id=user.id,
        created_at=now,
        expires_at=now + SESSION_TTL,
    )
    session.add(row)
    # Opportunistic cleanup: nobody else ever deletes expired rows.
    session.execute(sa_delete(AuthSession).where(AuthSession.expires_at < now))
    session.commit()
    return token, row


def resolve_session(session: Session, token: str) -> Store | None:
    """The shop a live token belongs to, or None if it is unknown or expired."""
    row = session.get(AuthSession, _token_hash(token))
    if row is None:
        return None
    if row.expires_at <= utc_now():
        session.delete(row)
        session.commit()
        return None
    return session.get(Store, row.store_id)


def revoke_session(session: Session, token: str) -> None:
    row = session.get(AuthSession, _token_hash(token))
    if row is not None:
        session.delete(row)
        session.commit()


def upsert_user(
    session: Session, store: Store, username: str, password: str
) -> StoreUser:
    """Create a login for ``store``, or reset its password if it exists.

    Changing a password signs that user out everywhere.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    name = normalise_username(username)
    if not name:
        raise ValueError("username must not be empty")

    user = session.exec(select(StoreUser).where(StoreUser.username == name)).first()
    if user is None:
        user = StoreUser(store_id=store.id, username=name, password_hash="")
    elif user.store_id != store.id:
        raise ValueError(f"username {name!r} already belongs to another shop")
    else:
        session.execute(
            sa_delete(AuthSession).where(AuthSession.user_id == user.id)
        )
    user.password_hash = hash_password(password)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
