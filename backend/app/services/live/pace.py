"""How today is going against the shop's usual day. Pure pandas, no I/O.

Compares today with the same weekday in past weeks, using complete days
only, so a half-finished day never lowers the baseline:

* band: p10 / p50 / p90 of *cumulative* sales at each hour -- the corridor a
  normal Wednesday runs through. Cumulative, because it is smooth and a
  shopkeeper reads "by 2pm I'm usually at Rs 3,000" instantly.
* pace: today's sales through the last *finished* hour against the typical
  sales by then. The hour in progress is left out; ten minutes of 14:00
  would always look like a slow hour.
* projection: today so far divided by the share of a usual day's takings
  that is normally in by this hour.
* the hour in progress, shown on its own with the usual for a whole hour.
* a conversion alert when the last hour's buying rate falls well below the
  usual for that hour, with a minimum number of visitors so noise is quiet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

WEEKDAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays",
            "Saturdays", "Sundays"]
#: Fewer same-weekday days than this and there is no honest band.
MIN_DAYS = 3
#: A pace inside this is "about usual" rather than ahead or behind.
PACE_NOISE = 0.05
#: Conversion alert: at least this many visitors, and below this share of usual.
ALERT_MIN_VISITORS = 8
ALERT_DROP = 0.6


@dataclass(frozen=True)
class BandPoint:
    hour: int
    p10: float
    p50: float
    p90: float
    #: Today's cumulative sales at the end of this hour; None for hours that
    #: have not happened yet.
    actual: float | None


@dataclass(frozen=True)
class HourNow:
    hour: int
    footfall: int
    transactions: int
    sales: float
    usual_footfall: float
    usual_transactions: float
    usual_sales: float


@dataclass(frozen=True)
class LiveView:
    weekday: str
    days_compared: int
    band: list[BandPoint]
    now: HourNow | None
    #: +0.18 means 18% ahead of the usual sales by the last finished hour.
    pace: float | None
    pace_through_hour: int | None
    projected_sales: float | None
    typical_sales: float
    alert: str | None
    #: Where "now" sits on the day, in hours since midnight (14.5 = 14:30),
    #: so the chart's line can end at the shop clock instead of an hour mark.
    clock_hour: float | None = None
    #: Today's sales up to that moment, the in-progress hour included.
    sales_so_far: float = 0.0


def _per_date_hour(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(["date", "hour"], as_index=False)[
        ["footfall", "transactions", "sales"]
    ].sum()


def _grid(per: pd.DataFrame, column: str) -> pd.DataFrame:
    """date x hour 0..23 table, missing hours as zero."""
    g = per.pivot_table(index="date", columns="hour", values=column,
                        aggfunc="sum", fill_value=0)
    return g.reindex(columns=range(24), fill_value=0)


def live_view(
    history: pd.DataFrame,
    today_df: pd.DataFrame,
    today: date,
    clock: datetime | None = None,
) -> LiveView | None:
    """``history``: rows for complete past days; ``today_df``: today's rows so far.

    ``clock`` is the shop's current time; without it "now" is the end of the
    latest hour that has data.
    """
    if history.empty or today_df.empty:
        return None
    hist = _per_date_hour(history)
    hist = hist[pd.to_datetime(hist["date"]).dt.dayofweek == today.weekday()]
    days = hist["date"].nunique()
    if days < MIN_DAYS:
        return None

    sales = _grid(hist, "sales")
    cum = sales.cumsum(axis=1)
    p10, p50, p90 = (cum.quantile(q) for q in (0.1, 0.5, 0.9))
    typical_total = float(sales.sum(axis=1).median())

    now_df = _per_date_hour(today_df)
    current = int(now_df["hour"].max())
    today_sales = _grid(now_df, "sales").iloc[0]
    today_cum = today_sales.cumsum()

    band = [
        BandPoint(
            hour=h,
            p10=round(float(p10[h]), 2),
            p50=round(float(p50[h]), 2),
            p90=round(float(p90[h]), 2),
            actual=round(float(today_cum[h]), 2) if h <= current else None,
        )
        for h in range(24)
    ]

    # Pace and projection use finished hours only.
    done = current - 1
    pace = projected = None
    usual_by_then = float(p50[done]) if done >= 0 else 0.0
    if done >= 0 and usual_by_then > 0:
        so_far = float(today_cum[done])
        pace = so_far / usual_by_then - 1
        share = usual_by_then / typical_total if typical_total else 0
        projected = so_far / share if share else None

    row = now_df[now_df["hour"] == current].iloc[0]
    ff_grid, tx_grid = _grid(hist, "footfall"), _grid(hist, "transactions")
    now = HourNow(
        hour=current,
        footfall=int(row["footfall"]),
        transactions=int(row["transactions"]),
        sales=round(float(row["sales"]), 2),
        usual_footfall=round(float(ff_grid[current].mean()), 1),
        usual_transactions=round(float(tx_grid[current].mean()), 1),
        usual_sales=round(float(sales[current].mean()), 2),
    )

    def hour_stats(h: int) -> HourNow:
        r = now_df[now_df["hour"] == h]
        return HourNow(
            hour=h,
            footfall=int(r["footfall"].sum()),
            transactions=int(r["transactions"].sum()),
            sales=round(float(r["sales"].sum()), 2),
            usual_footfall=round(float(ff_grid[h].mean()), 1),
            usual_transactions=round(float(tx_grid[h].mean()), 1),
            usual_sales=round(float(sales[h].mean()), 2),
        )

    at = _clock_hour(clock, today, current)
    finished = int(at) - 1          # 20.3 (20:18) -> the 19:00 hour
    return LiveView(
        clock_hour=at,
        last_hour=hour_stats(finished) if 0 <= finished <= 23 else None,
        sales_so_far=round(float(today_cum[23]), 2),
        weekday=WEEKDAYS[today.weekday()],
        days_compared=int(days),
        band=band,
        now=now,
        pace=round(pace, 4) if pace is not None else None,
        pace_through_hour=done if pace is not None else None,
        projected_sales=round(projected, 2) if projected is not None else None,
        typical_sales=round(typical_total, 2),
        alert=conversion_alert(now_df, hist, current),
    )


def _clock_hour(clock: datetime | None, today: date, current: int) -> float:
    """Hours since midnight at the shop clock, never behind the data."""
    if clock is None or clock.date() < today:
        return float(current + 1)
    if clock.date() > today:
        return 24.0
    at = clock.hour + clock.minute / 60 + clock.second / 3600
    # Data already recorded for a later hour (an uploaded full day, say):
    # "now" is the end of that hour, not somewhere behind it.
    return round(at if int(at) >= current else float(current + 1), 4)


def conversion_alert(now_df: pd.DataFrame, hist: pd.DataFrame, current: int) -> str | None:
    """Flag the last finished hour if far fewer visitors bought than usual."""
    hour = current - 1
    last = now_df[now_df["hour"] == hour]
    if last.empty:
        return None
    visitors, bills = int(last["footfall"].sum()), int(last["transactions"].sum())
    usual = hist[hist["hour"] == hour]
    usual_ff = float(usual["footfall"].sum())
    if visitors < ALERT_MIN_VISITORS or usual_ff <= 0:
        return None
    usual_rate = float(usual["transactions"].sum()) / usual_ff
    rate = bills / visitors
    if usual_rate > 0 and rate < usual_rate * ALERT_DROP:
        return (
            f"Only {rate:.0%} of the {visitors} people who came in at {hour}:00 bought, "
            f"against {usual_rate:.0%} usually at that hour. "
            "Worth checking the queue or the shelves."
        )
    return None
