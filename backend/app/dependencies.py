from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session as DBSession

from .db import get_session
from .models import Store
from .services.auth import resolve_session

# auto_error=False so a missing header gets our own 401 (with the header the
# spec requires) instead of FastAPI's 403. Also adds "Authorize" to /docs.
bearer = HTTPBearer(auto_error=False)


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def bearer_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> Optional[str]:
    return creds.credentials.strip() if creds and creds.credentials else None


def get_current_store(
    token: Optional[str] = Depends(bearer_token),
    db: DBSession = Depends(get_session),
) -> Store:
    if not token:
        raise _unauthorised("Not logged in")
    store = resolve_session(db, token)
    if store is None:
        raise _unauthorised("Your session has ended. Log in again.")
    return store


def own_store_code(requested: Optional[str], store: Store) -> str:
    """Resolve a ``store_id`` query/body value against the logged-in shop.

    Omitted (or the old "all") means "my shop". Naming another shop is refused
    rather than silently swapped, so a stale client fails loudly.
    """
    if requested in (None, "", "all") or requested == store.code:
        return store.code
    raise HTTPException(403, "You can only see and change your own shop")
