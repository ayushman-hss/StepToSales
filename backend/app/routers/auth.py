import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session as DBSession

from ..db import get_session
from ..dependencies import get_current_store
from ..models import Session as AuthSession, Store, StoreUser
from ..services.auth import SESSION_TTL, authenticate

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    store_code: str
    store_name: str


class MeOut(BaseModel):
    store_code: str
    store_name: str


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, db: DBSession = Depends(get_session)):
    user = authenticate(db, body.username, body.password)
    if not user:
        raise HTTPException(401, "Wrong username or password")

    store = db.get(Store, user.store_id)
    if not store:
        raise HTTPException(500, "Store missing")

    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        token=token,
        store_id=store.id,
        expires_at=datetime.utcnow() + SESSION_TTL,
    ))
    db.commit()
    return LoginOut(token=token, store_code=store.code, store_name=store.name or store.code)


@router.post("/logout")
def logout(
    authorization: str | None = None,
    db: DBSession = Depends(get_session),
):
    # Best-effort: even if the header is missing, succeed.
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        row = db.get(AuthSession, token)
        if row:
            db.delete(row)
            db.commit()
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(store: Store = Depends(get_current_store)):
    return MeOut(store_code=store.code, store_name=store.name or store.code)