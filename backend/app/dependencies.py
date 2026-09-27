from datetime import datetime

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session as DBSession, select

from .db import get_session
from .models import Session as AuthSession, Store


def get_current_store(
    authorization: str | None = Header(default=None),
    db: DBSession = Depends(get_session),
) -> Store:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not logged in")

    token = authorization.removeprefix("Bearer ").strip()
    row = db.get(AuthSession, token)
    if row is None:
        raise HTTPException(401, "Session not found")
    if row.expires_at < datetime.utcnow():
        db.delete(row)
        db.commit()
        raise HTTPException(401, "Session expired")

    store = db.get(Store, row.store_id)
    if store is None:
        raise HTTPException(401, "Store not found")
    return store