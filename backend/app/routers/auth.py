from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session as DBSession

from ..db import get_session
from ..dependencies import bearer_token, get_current_store
from ..models import Store
from ..services.auth import authenticate, create_session, revoke_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class StoreInfo(BaseModel):
    store_code: str
    store_name: str


class LoginOut(StoreInfo):
    token: str
    expires_at: str


def _info(store: Store) -> dict:
    return {"store_code": store.code, "store_name": store.name or store.code}


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, db: DBSession = Depends(get_session)):
    user = authenticate(db, body.username, body.password)
    if not user:
        raise HTTPException(401, "Wrong username or password")

    store = db.get(Store, user.store_id)
    if not store:
        raise HTTPException(500, "Store missing")

    token, row = create_session(db, user)
    return LoginOut(
        token=token,
        expires_at=row.expires_at.isoformat(timespec="seconds") + "Z",
        **_info(store),
    )


@router.post("/logout")
def logout(
    token: Optional[str] = Depends(bearer_token),
    db: DBSession = Depends(get_session),
):
    # Best-effort: logging out with a missing or dead token still succeeds,
    # so the browser can always clear its copy.
    if token:
        revoke_session(db, token)
    return {"ok": True}


@router.get("/me", response_model=StoreInfo)
def me(store: Store = Depends(get_current_store)):
    return StoreInfo(**_info(store))
