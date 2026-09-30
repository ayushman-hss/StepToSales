"""What is worth a message on the shopkeeper's phone, and what it says.

Pure functions over the live view: no database, no Telegram. Each alert has
a ``kind`` and a ``key``; the pair is what makes it happen once -- one
conversion alert per hour, one pace warning and one closing summary per day.

Kept deliberately few. A phone that buzzes every hour gets muted, and then
the one alert that mattered is missed too.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ..live.pace import LiveView
from ..live.today import DayTotals

#: Warn once a day when sales are at least this far behind the usual pace...
BEHIND_PACE = -0.25
#: ...but only once a usual day would have taken this share of its sales,
#: so a slow first hour does not cry wolf.
BEHIND_MIN_SHARE = 0.25
#: A conversion alert about an hour that ended longer ago than this (shop
#: time) is stale -- e.g. found while catching up after downtime -- and skipped.
FRESH_HOURS = 2.0


@dataclass(frozen=True)
class Alert:
    kind: str
    key: str
    text: str


def inr(amount: float) -> str:
    """Rs in the Indian grouping a shopkeeper reads: 1,23,456."""
    n = int(round(amount))
    sign, n = ("-" if n < 0 else ""), abs(n)
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"{sign}₹{s}"


def clock_hour(clock: datetime) -> float:
    return clock.hour + clock.minute / 60 + clock.second / 3600


def _singular(weekday: str) -> str:
    return weekday[:-1] if weekday.endswith("s") else weekday


def usual_close_hour(view: LiveView) -> int | None:
    """When a usual day stops taking money: the end of its last trading hour."""
    last, before = None, 0.0
    for point in view.band:
        if point.p50 > before + 0.005:
            last = point.hour
        before = point.p50
    return None if last is None else last + 1


def due_alerts(view: LiveView, day: date, now_hour: float,
               totals: DayTotals) -> list[Alert]:
    """Alerts that apply right now. The caller drops ones already sent."""
    out: list[Alert] = []
    d = day.isoformat()
    usual = _singular(view.weekday)

    # 1. Far fewer buyers than usual in the hour that just ended.
    if view.alert and view.now is not None:
        hour = view.now.hour - 1
        if 0 <= now_hour - (hour + 1) <= FRESH_HOURS:
            out.append(Alert("conversion_drop", f"{d}T{hour:02d}", view.alert))

    # 2. Well behind a usual day, once there is enough of the day to judge.
    h = view.pace_through_hour
    if view.pace is not None and h is not None and view.pace <= BEHIND_PACE:
        usual_by = view.band[h].p50
        so_far = view.band[h].actual or 0.0
        if view.typical_sales > 0 and usual_by / view.typical_sales >= BEHIND_MIN_SHARE:
            likely = (
                f" At this rate, about {inr(view.projected_sales)} by closing"
                f" against a usual {inr(view.typical_sales)}."
                if view.projected_sales is not None else ""
            )
            out.append(Alert(
                "behind_pace", d,
                f"Sales are {round(-view.pace * 100)}% behind a usual {usual}: "
                f"{inr(so_far)} by {h + 1}:00, when you would normally have about "
                f"{inr(usual_by)}.{likely}",
            ))

    # 3. The day's summary, once the usual closing time has passed.
    close = usual_close_hour(view)
    if close is not None and now_hour >= min(close, 23.99):  # open till midnight
        out.append(Alert("day_summary", d, day_summary(view, totals)))

    return out


def day_summary(view: LiveView, totals: DayTotals) -> str:
    usual = _singular(view.weekday)
    lines = [f"Today's close: {inr(totals.sales)}."]
    if view.typical_sales > 0:
        diff = totals.sales / view.typical_sales - 1
        pct = round(abs(diff) * 100)
        if pct < 5:
            lines.append(f"About a usual {usual} ({inr(view.typical_sales)}).")
        else:
            word = "above" if diff > 0 else "below"
            lines.append(f"{pct}% {word} a usual {usual} ({inr(view.typical_sales)}).")
    if totals.footfall:
        rate = totals.transactions / totals.footfall
        lines.append(
            f"{totals.transactions} bills from {totals.footfall} visitors "
            f"({rate:.0%} bought)."
        )
    if totals.by_hour:
        best = max(totals.by_hour, key=lambda k: totals.by_hour[k])
        if totals.by_hour[best] > 0:
            lines.append(f"Best hour: {best}:00, {inr(totals.by_hour[best])}.")
    return "\n".join(lines)


def status_text(view: LiveView | None, totals: DayTotals | None, clock: datetime) -> str:
    """The reply to /status: how today is going, in three lines."""
    at = f"{clock.hour}:{clock.minute:02d}"
    if view is None or totals is None:
        return f"No sales recorded yet today (shop clock {at})."
    lines = [
        f"{inr(totals.sales)} sold by {at}: {totals.transactions} bills, "
        f"{totals.footfall} visitors."
    ]
    if view.pace is not None and view.pace_through_hour is not None:
        pct = round(abs(view.pace) * 100)
        by = f"by {view.pace_through_hour + 1}:00"
        usual = _singular(view.weekday)
        if pct < 5:
            lines.append(f"On your usual pace {by}.")
        else:
            word = "ahead of" if view.pace > 0 else "behind"
            lines.append(f"{pct}% {word} a usual {usual} {by}.")
    if view.projected_sales is not None:
        lines.append(f"Likely {inr(view.projected_sales)} by closing.")
    return "\n".join(lines)
