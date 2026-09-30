"""A shop that keeps trading: visitors arrive, some buy, baskets are real.

The history was generated sales-first with footfall modelled around it. Live
mode runs the other way round -- a visitor arrives, then buys or does not --
so the simulator is *calibrated from the shop's own history* rather than
re-implementing the generator's rules:

* visitors per hour: the historical average for that weekday and hour;
* chance of buying: the historical conversion for that hour of day;
* what they buy: a whole basket drawn from the shop's recorded bills in that
  hour of day, at the price actually paid.

So today's line lands inside the band drawn from past weeks by construction,
and the bundle engine keeps seeing the same product pairings.

Pure apart from ``calibrate``: given a calibration, a time window and a seeded
``random.Random``, ``simulate`` returns the same events every time.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd
from sqlmodel import Session, select

from ...models import HourlyData, SaleLine, Store

#: How much history to learn from. Long enough to cover every weekday several
#: times, short enough to follow a change in the shop.
CALIBRATION_WEEKS = 8
#: Baskets kept per hour of day. Plenty for variety, small enough to hold.
MAX_BASKETS_PER_HOUR = 400


@dataclass(frozen=True)
class Line:
    sku: str
    qty: int
    unit_price_paise: int


@dataclass
class Calibration:
    store_code: str
    #: (weekday 0=Mon, hour) -> average visitors in that hour.
    visitors: dict[tuple[int, int], float] = field(default_factory=dict)
    #: hour -> share of visitors who bought, over the whole history.
    conversion: dict[int, float] = field(default_factory=dict)
    #: hour -> recorded baskets; hour -1 holds all of them as a fallback.
    baskets: dict[int, list[tuple[Line, ...]]] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return bool(self.visitors) and bool(self.baskets.get(-1))


@dataclass(frozen=True)
class SimEvent:
    event_id: str
    kind: str                     # "visit" | "bill"
    ts: datetime
    lines: tuple[Line, ...] = ()

    @property
    def amount_paise(self) -> int:
        return sum(line.qty * line.unit_price_paise for line in self.lines)


def to_paise(rupees: float) -> int:
    return int(round(float(rupees) * 100))


def calibrate(session: Session, store: Store, today: date) -> Calibration:
    """Learn the shop's rhythm from its last few weeks of complete days."""
    since = (today - timedelta(weeks=CALIBRATION_WEEKS)).isoformat()
    until = today.isoformat()
    cal = Calibration(store_code=store.code)

    rows = session.exec(
        select(HourlyData.date, HourlyData.hour, HourlyData.footfall, HourlyData.transactions)
        .where(HourlyData.store_id == store.id)
        .where(HourlyData.date >= since)
        .where(HourlyData.date < until)
    ).all()
    if rows:
        df = pd.DataFrame(rows, columns=["date", "hour", "footfall", "transactions"])
        per = df.groupby(["date", "hour"], as_index=False)[["footfall", "transactions"]].sum()
        per["dow"] = pd.to_datetime(per["date"]).dt.dayofweek
        # Divide by how many of that weekday are in the window, not by how
        # many had a row: a closed hour is zero visitors, not missing data.
        days = pd.Series(pd.to_datetime(per["date"].unique())).dt.dayofweek.value_counts()
        visitors = per.groupby(["dow", "hour"])["footfall"].sum()
        cal.visitors = {
            (int(dow), int(hour)): float(total) / int(days[dow])
            for (dow, hour), total in visitors.items()
        }
        by_hour = per.groupby("hour")[["footfall", "transactions"]].sum()
        cal.conversion = {
            int(h): min(1.0, float(r["transactions"]) / float(r["footfall"]))
            for h, r in by_hour.iterrows()
            if r["footfall"] > 0
        }

    lines = session.exec(
        select(SaleLine.hour, SaleLine.upload_id, SaleLine.transaction_id,
               SaleLine.sku, SaleLine.qty, SaleLine.unit_price)
        .where(SaleLine.store_id == store.id)
        .where(SaleLine.date >= since)
        .where(SaleLine.date < until)
    ).all()
    grouped: dict[tuple[int, str], list[Line]] = {}
    hour_of: dict[tuple[int, str], int] = {}
    for hour, upload_id, tx, sku, qty, price in lines:
        key = (upload_id, tx)
        grouped.setdefault(key, []).append(Line(sku, int(qty), to_paise(price)))
        hour_of[key] = int(hour)

    rng = random.Random(f"baskets:{store.code}")  # stable subsample
    all_baskets = [tuple(v) for v in grouped.values()]
    by_hour_baskets: dict[int, list[tuple[Line, ...]]] = {}
    for key, basket in zip(grouped.keys(), all_baskets):
        by_hour_baskets.setdefault(hour_of[key], []).append(basket)
    for hour, baskets in by_hour_baskets.items():
        if len(baskets) > MAX_BASKETS_PER_HOUR:
            baskets = rng.sample(baskets, MAX_BASKETS_PER_HOUR)
        cal.baskets[hour] = baskets
    if all_baskets:
        cal.baskets[-1] = (
            rng.sample(all_baskets, MAX_BASKETS_PER_HOUR)
            if len(all_baskets) > MAX_BASKETS_PER_HOUR
            else all_baskets
        )
    return cal


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method; the per-slice rates here are small (well under 50)."""
    if lam <= 0:
        return 0
    if lam > 50:  # normal approximation, never hit at shop scale
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _event_id(rng: random.Random, store_code: str) -> str:
    return f"sim-{store_code}-{rng.getrandbits(64):016x}"


def simulate(
    cal: Calibration, start: datetime, end: datetime, rng: random.Random,
    visitors_factor: float = 1.0, conversion_factor: float = 1.0,
) -> list[SimEvent]:
    """Everything that happens in the shop in ``[start, end)``, in time order.

    The window is cut at hour boundaries, so the rate always matches the hour
    an arrival falls in. The factors bend the shop's usual rhythm for a demo
    (a slow or a busy day); 1.0 is the shop as its history says.
    """
    events: list[SimEvent] = []
    if not cal.usable or end <= start:
        return events

    t = start
    while t < end:
        hour_end = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        seg_end = min(end, hour_end)
        seconds = (seg_end - t).total_seconds()
        rate = cal.visitors.get((t.weekday(), t.hour), 0.0) * visitors_factor
        arrivals = _poisson(rng, rate * seconds / 3600)
        convert = min(1.0, cal.conversion.get(t.hour, 0.0) * conversion_factor)
        pool = cal.baskets.get(t.hour) or cal.baskets[-1]

        times = sorted(t + timedelta(seconds=rng.random() * seconds) for _ in range(arrivals))
        for at in times:
            at = at.replace(microsecond=0)
            events.append(SimEvent(_event_id(rng, cal.store_code), "visit", at))
            if rng.random() < convert:
                basket = rng.choice(pool)
                # A bill takes a moment after walking in, but never spills
                # into the next hour -- that would move money between hours.
                paid = min(at + timedelta(seconds=rng.randint(20, 240)),
                           seg_end - timedelta(seconds=1))
                events.append(SimEvent(_event_id(rng, cal.store_code), "bill", paid, basket))
        t = seg_end

    events.sort(key=lambda e: e.ts)
    return events
