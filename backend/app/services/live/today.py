"""Today's live view for one shop, straight from the database.

The dashboard builds the same view for the page; the alert watcher needs it
without a request, for every shop, every few seconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from sqlmodel import Session, select

from ...models import HourlyData, Store
from .pace import LiveView, live_view

#: How far back "a usual Wednesday" looks -- the same as the dashboard.
HISTORY_DAYS = 56


@dataclass(frozen=True)
class DayTotals:
    footfall: int
    transactions: int
    sales: float
    #: Sales per hour so far today, for "best hour".
    by_hour: dict[int, float]


def _hourly(session: Session, store: Store, start: str, end: str) -> pd.DataFrame:
    rows = session.exec(
        select(HourlyData.date, HourlyData.hour, HourlyData.footfall,
               HourlyData.transactions, HourlyData.sales)
        .where(HourlyData.store_id == store.id)
        .where(HourlyData.date >= start)
        .where(HourlyData.date <= end)
    ).all()
    return pd.DataFrame([dict(r._mapping) for r in rows]) if rows else pd.DataFrame()


def today_view(session: Session, store: Store, clock: datetime
               ) -> tuple[LiveView | None, DayTotals | None]:
    """How ``store`` is doing on the day of ``clock`` (shop time, IST)."""
    day = clock.date()
    today = _hourly(session, store, day.isoformat(), day.isoformat())
    if today.empty:
        return None, None
    history = _hourly(
        session, store,
        (day - timedelta(days=HISTORY_DAYS)).isoformat(),
        (day - timedelta(days=1)).isoformat(),
    )
    view = live_view(history, today, day, clock)
    by_hour = today.groupby("hour")["sales"].sum()
    totals = DayTotals(
        footfall=int(today["footfall"].sum()),
        transactions=int(today["transactions"].sum()),
        sales=round(float(today["sales"].sum()), 2),
        by_hour={int(h): float(v) for h, v in by_hour.items()},
    )
    return view, totals
