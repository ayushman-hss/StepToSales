"""Ask the shop assistant from the web app -- the same answers the Telegram
bot gives, for the logged-in shop."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..alerts import alerts
from ..db import get_session
from ..dependencies import get_current_store
from ..live import runner
from ..models import Store
from ..services.assistant.answers import answer

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)


class Answer(BaseModel):
    answer: str


@router.post("/ask", response_model=Answer)
def ask(
    body: Question,
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    clock = alerts.shop_clock(current.code) or runner.shop_now(current.code)
    return Answer(answer=answer(session, current, body.question, clock))
