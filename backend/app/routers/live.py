"""Live mode for the logged-in shop: its clock, its speed, and its till.

Everything here is scoped to the session's shop, like the rest of the API.
A till request never names a shop -- it rings up for whoever is logged in.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from ..db import get_session
from ..dependencies import get_current_store
from ..live import runner
from ..models import AlertSent, LiveEvent, Product, Store
from ..services.live.clock import ist_now
from ..services.live.engine import IncomingEvent, clear_day, last_event_time, record
from ..services.live.runner import SCENARIOS, SPEEDS
from ..services.live.simulator import Line, to_paise

router = APIRouter(prefix="/api/live", tags=["live"])


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat(timespec="seconds") if t else None


class LiveStatus(BaseModel):
    #: The simulator is running in this API process.
    running: bool
    #: 0 paused, 1 real time, 10 / 60 / 300 fast-forward.
    speed: int
    #: Demo day: "normal", "slow" or "busy".
    scenario: str = "normal"
    #: The shop's clock (IST). Ahead of real_time while fast-forwarding.
    shop_time: str
    real_time: str
    minutes_ahead: int
    last_event_at: Optional[str]
    last_bill_at: Optional[str]
    bills_today: int
    visitors_today: int


def _status(session: Session, store: Store) -> LiveStatus:
    real = ist_now()
    shop = runner.state(store.code)
    shop_time = runner.shop_now(store.code)
    today = shop_time.date().isoformat()
    counts = dict(
        session.exec(
            select(LiveEvent.kind, func.count())
            .where(LiveEvent.store_id == store.id)
            .where(LiveEvent.date == today)
            .group_by(LiveEvent.kind)
        ).all()
    )
    return LiveStatus(
        running=runner.running and shop is not None,
        speed=shop.speed if shop else 0,
        scenario=shop.scenario if shop else "normal",
        shop_time=_iso(shop_time),
        real_time=_iso(real),
        minutes_ahead=max(0, int((shop_time - real).total_seconds() // 60)),
        last_event_at=_iso(last_event_time(session, store)),
        last_bill_at=_iso(last_event_time(session, store, "bill")),
        bills_today=int(counts.get("bill", 0)),
        visitors_today=int(counts.get("visit", 0)),
    )


@router.get("/status", response_model=LiveStatus)
def status(
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    return _status(session, store)


class SpeedIn(BaseModel):
    speed: int


@router.post("/speed", response_model=LiveStatus)
def set_speed(
    body: SpeedIn,
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    if body.speed not in SPEEDS:
        raise HTTPException(400, f"speed must be one of {list(SPEEDS)}")
    if runner.set_speed(store.code, body.speed) is None:
        raise HTTPException(409, "The live simulator is not running for this shop")
    return _status(session, store)


class ScenarioIn(BaseModel):
    scenario: str


@router.post("/scenario", response_model=LiveStatus)
def set_scenario(
    body: ScenarioIn,
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    """Make the rest of the simulated day slow or busy -- for demos."""
    if body.scenario not in SCENARIOS:
        raise HTTPException(400, f"scenario must be one of {list(SCENARIOS)}")
    if runner.set_scenario(store.code, body.scenario) is None:
        raise HTTPException(409, "The live simulator is not running for this shop")
    return _status(session, store)


def _clear_today(session: Session, store: Store, day: str) -> None:
    clear_day(session, store, day)
    # Today's alerts go too, so the replayed day can raise them again.
    # Alert keys start with the day ("2026-09-30" or "2026-09-30T14").
    for row in session.exec(
        select(AlertSent).where(AlertSent.store_id == store.id)
        .where(AlertSent.key.startswith(day))
    ).all():
        session.delete(row)


@router.post("/reset", response_model=LiveStatus)
def reset_today(
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    """Start this shop's day again, for demos: today's live bills, visits and
    alerts are removed, and the day is replayed from midnight at real time on
    a usual day. Uploaded history and connected phones are kept."""
    if runner.reset_today(store.code, _clear_today) is None:
        raise HTTPException(404, "Unknown shop")
    session.expire_all()
    return _status(session, store)


# ---- the till ------------------------------------------------------------


class TillLine(BaseModel):
    sku: str
    qty: int = Field(ge=1, le=99)


class BillIn(BaseModel):
    #: Made by the browser once per bill, so a retried or double-tapped
    #: request is recorded once.
    event_id: str = Field(min_length=8, max_length=80)
    lines: list[TillLine] = Field(min_length=1, max_length=30)
    #: A customer who buys also walked in. Off only if the door was already
    #: counted with the visitor button.
    count_visitor: bool = True


class VisitIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=80)


class TillReceipt(BaseModel):
    recorded: bool
    amount_paise: int
    at: str


@router.post("/bill", response_model=TillReceipt)
def ring_bill(
    body: BillIn,
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    skus = {line.sku for line in body.lines}
    prices = {
        p.sku: to_paise(p.sell_price)
        for p in session.exec(
            select(Product).where(Product.store_id == store.id).where(Product.sku.in_(skus))
        ).all()
    }
    missing = sorted(skus - prices.keys())
    if missing:
        raise HTTPException(400, f"Not in your price list: {', '.join(missing)}")

    lines = tuple(Line(x.sku, x.qty, prices[x.sku]) for x in body.lines)
    at = runner.shop_now(store.code)
    events = [IncomingEvent(f"pos-{body.event_id}", "bill", at, "pos", lines)]
    if body.count_visitor:
        events.insert(0, IncomingEvent(f"pos-{body.event_id}-v", "visit", at, "pos"))
    added = record(session, store, events)
    return TillReceipt(
        recorded=added > 0,
        amount_paise=sum(x.qty * x.unit_price_paise for x in lines),
        at=_iso(at),
    )


@router.post("/visit", response_model=TillReceipt)
def count_visit(
    body: VisitIn,
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    at = runner.shop_now(store.code)
    added = record(session, store, [IncomingEvent(f"pos-{body.event_id}", "visit", at, "pos")])
    return TillReceipt(recorded=added > 0, amount_paise=0, at=_iso(at))


class RecentBill(BaseModel):
    at: str
    source: str
    amount_paise: int
    items: int
    lines: list[dict]


@router.get("/bills", response_model=list[RecentBill])
def recent_bills(
    limit: int = 10,
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    rows = session.exec(
        select(LiveEvent)
        .where(LiveEvent.store_id == store.id)
        .where(LiveEvent.kind == "bill")
        .order_by(LiveEvent.ts.desc(), LiveEvent.id.desc())
        .limit(max(1, min(limit, 50)))
    ).all()
    names = {
        p.sku: p.name
        for p in session.exec(select(Product).where(Product.store_id == store.id)).all()
    }
    out = []
    for r in rows:
        lines = json.loads(r.lines or "[]")
        for line in lines:
            line["name"] = names.get(line["sku"], line["sku"])
        out.append(RecentBill(
            at=_iso(r.ts), source=r.source, amount_paise=r.amount_paise,
            items=sum(int(x["qty"]) for x in lines), lines=lines,
        ))
    return out
