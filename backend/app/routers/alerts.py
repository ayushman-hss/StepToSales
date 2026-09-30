"""Phone alerts for the logged-in shop: its Telegram chats and its alert feed.

Scoped to the session's shop like every other route -- a request never names
a shop, and a chat id from another shop is a 404.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..alerts import alerts
from ..db import get_session
from ..dependencies import get_current_store
from ..models import AlertChat, AlertSent, Store
from ..services.alerts.rules import HOURLY
from ..services.alerts.service import COMMANDS_HELP, WHAT_YOU_GET

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class TelegramState(BaseModel):
    #: A bot token is set on the server.
    configured: bool
    bot_username: Optional[str] = None
    #: The last problem reaching Telegram, in words.
    error: Optional[str] = None


class ChatOut(BaseModel):
    id: int
    title: str
    hourly: bool
    linked_at: datetime


class ChatUpdate(BaseModel):
    hourly: bool


class AlertOut(BaseModel):
    id: int
    kind: str
    text: str
    shop_time: datetime
    delivered: int


class AlertsOverview(BaseModel):
    telegram: TelegramState
    chats: List[ChatOut]
    recent: List[AlertOut]


class LinkOut(BaseModel):
    code: str
    #: Opens the bot with the code filled in; None until the bot's name is known.
    url: Optional[str] = None
    bot_username: Optional[str] = None
    expires_at: datetime


class TestOut(BaseModel):
    delivered: int


@router.get("", response_model=AlertsOverview)
def overview(
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    chats = session.exec(
        select(AlertChat).where(AlertChat.store_id == current.id).order_by(AlertChat.linked_at)
    ).all()
    recent = session.exec(
        select(AlertSent)
        .where(AlertSent.store_id == current.id)
        .where(AlertSent.kind != HOURLY)        # routine, not news
        .order_by(AlertSent.shop_time.desc(), AlertSent.id.desc())
        .limit(20)
    ).all()
    return AlertsOverview(
        telegram=TelegramState(
            configured=alerts.configured,
            bot_username=alerts.bot_username,
            error=alerts.bot_error,
        ),
        chats=[ChatOut(id=c.id, title=c.title, hourly=c.hourly, linked_at=c.linked_at)
               for c in chats],
        recent=[
            AlertOut(id=a.id, kind=a.kind, text=a.text, shop_time=a.shop_time,
                     delivered=a.delivered)
            for a in recent
        ],
    )


@router.post("/telegram/link", response_model=LinkOut)
def new_link(
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    """A one-time link that connects a Telegram chat to this shop."""
    if not alerts.configured:
        raise HTTPException(400, "Telegram is not set up on the server yet.")
    code = alerts.new_link_code(session, current)
    return LinkOut(code=code.code, url=alerts.link_url(code.code),
                   bot_username=alerts.bot_username, expires_at=code.expires_at)


def _own_chat(session: Session, current: Store, chat_id: int) -> AlertChat:
    row = session.get(AlertChat, chat_id)
    if row is None or row.store_id != current.id:
        raise HTTPException(404, "Chat not found")
    return row


@router.patch("/chats/{chat_id}", response_model=ChatOut)
def update_chat(
    chat_id: int,
    body: ChatUpdate,
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    row = _own_chat(session, current, chat_id)
    row.hourly = body.hourly
    session.add(row)
    session.commit()
    return ChatOut(id=row.id, title=row.title, hourly=row.hourly, linked_at=row.linked_at)


@router.delete("/chats/{chat_id}")
def remove_chat(
    chat_id: int,
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    row = _own_chat(session, current, chat_id)
    session.delete(row)
    session.commit()
    return {"ok": True}


@router.post("/test", response_model=TestOut)
def send_test(
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    if not alerts.configured:
        raise HTTPException(400, "Telegram is not set up on the server yet.")
    delivered = alerts.send_to_shop(
        session, current,
        f"\u2705 Test from StepToSales: alerts for {current.code} \u00b7 {current.name} "
        f"will arrive in this chat.\n\n{WHAT_YOU_GET}\n\n{COMMANDS_HELP}",
    )
    if delivered == 0:
        raise HTTPException(400, "No connected chat got the message. Connect Telegram first.")
    return TestOut(delivered=delivered)
