"""Write live events and roll them into the tables the dashboard reads.

``live_event`` is the truth. For every hour it touches, the shop gets one
``hourly_data`` row owned by the live upload, recomputed from the events --
never incremented -- so it cannot drift. Bills also become ``sale_line`` rows,
so bundle suggestions learn from live bills exactly as from uploaded ones.

The dashboard already adds up every row for a (date, hour), so the live row
simply sits beside whatever history exists for that hour.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import Session, select

from ...models import HourlyData, LiveEvent, SaleLine, Store, Upload
from .simulator import Line, SimEvent

LIVE_UPLOAD = "live-events"


@dataclass(frozen=True)
class IncomingEvent:
    """What any source -- simulator or till -- hands to ``record``."""
    event_id: str
    kind: str                     # "visit" | "bill"
    ts: object                    # naive IST datetime
    source: str
    lines: tuple[Line, ...] = ()

    @classmethod
    def from_sim(cls, e: SimEvent) -> "IncomingEvent":
        return cls(e.event_id, e.kind, e.ts, "sim", e.lines)


def live_upload(session: Session) -> Upload:
    """The single ``upload`` row every live row hangs off."""
    row = session.exec(select(Upload).where(Upload.filename == LIVE_UPLOAD)).first()
    if row is None:
        row = Upload(filename=LIVE_UPLOAD, rows=0)
        session.add(row)
        session.flush()
    return row


def record(session: Session, store: Store, events: Iterable[IncomingEvent]) -> int:
    """Store new events, derive their rows, and commit. Returns how many were new.

    Idempotent: an event whose id is already stored (a retried request, a
    double tap) is skipped, so nothing is counted twice.
    """
    events = list(events)
    if not events:
        return 0
    ids = [e.event_id for e in events]
    seen = set(
        session.exec(select(LiveEvent.event_id).where(LiveEvent.event_id.in_(ids))).all()
    )
    upload = live_upload(session)
    touched: set[tuple[str, int]] = set()
    added = 0
    for e in events:
        if e.event_id in seen:
            continue
        seen.add(e.event_id)
        day, hour = e.ts.date().isoformat(), e.ts.hour
        amount = sum(line.qty * line.unit_price_paise for line in e.lines)
        session.add(LiveEvent(
            event_id=e.event_id, store_id=store.id, kind=e.kind, source=e.source,
            ts=e.ts, date=day, hour=hour, amount_paise=amount,
            lines=json.dumps([
                {"sku": x.sku, "qty": x.qty, "unit_price_paise": x.unit_price_paise}
                for x in e.lines
            ]),
        ))
        if e.kind == "bill":
            session.add_all([
                SaleLine(
                    store_id=store.id, upload_id=upload.id, date=day, hour=hour,
                    transaction_id=e.event_id, sku=x.sku, qty=x.qty,
                    unit_price=x.unit_price_paise / 100,
                )
                for x in e.lines
            ])
        touched.add((day, hour))
        added += 1

    session.flush()
    for day, hour in sorted(touched):
        rollup_hour(session, store, upload, day, hour)
    upload.rows = (upload.rows or 0) + added
    session.add(upload)
    session.commit()
    return added


def rollup_hour(session: Session, store: Store, upload: Upload, day: str, hour: int) -> HourlyData:
    """Recompute one hour's live row from its events."""
    kinds = dict(
        session.exec(
            select(LiveEvent.kind, func.count())
            .where(LiveEvent.store_id == store.id)
            .where(LiveEvent.date == day)
            .where(LiveEvent.hour == hour)
            .group_by(LiveEvent.kind)
        ).all()
    )
    paise = session.exec(
        select(func.coalesce(func.sum(LiveEvent.amount_paise), 0))
        .where(LiveEvent.store_id == store.id)
        .where(LiveEvent.date == day)
        .where(LiveEvent.hour == hour)
        .where(LiveEvent.kind == "bill")
    ).one()

    row = session.exec(
        select(HourlyData)
        .where(HourlyData.store_id == store.id)
        .where(HourlyData.upload_id == upload.id)
        .where(HourlyData.date == day)
        .where(HourlyData.hour == hour)
    ).first()
    if row is None:
        row = HourlyData(store_id=store.id, upload_id=upload.id, date=day, hour=hour,
                         footfall=0, transactions=0, sales=0.0)
    row.footfall = int(kinds.get("visit", 0))
    row.transactions = int(kinds.get("bill", 0))
    row.sales = int(paise) / 100
    session.add(row)
    return row


def last_event_time(session: Session, store: Store, kind: str | None = None):
    stmt = select(func.max(LiveEvent.ts)).where(LiveEvent.store_id == store.id)
    if kind:
        stmt = stmt.where(LiveEvent.kind == kind)
    return session.exec(stmt).first()
