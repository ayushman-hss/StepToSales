"""What is worth a message on the shopkeeper's phone, and what it says.

Pure functions over the live view: no database, no Telegram. Each alert has
a ``kind`` and a ``key``; the pair is what makes it happen once.

* Per finished hour, at most one message: a **slow hour** (fewer people came
  in, or fewer of them bought) or a **busy hour** (well above the usual).
* Per day: **behind pace** or **ahead of pace**, and the **day's summary**
  after the usual closing time.
* Optional, per chat: an **hourly update** after every trading hour.

The thresholds are set so an ordinary day stays quiet. A phone that buzzes
for nothing gets muted, and then the alert that mattered is missed too.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ..live.pace import HourNow, LiveView
from ..live.today import DayTotals

#: Once a day, when sales are this far behind (or ahead of) the usual pace...
BEHIND_PACE = -0.25
AHEAD_PACE = 0.20
#: ...and only once a usual day would have taken this share of its sales, so
#: a slow or lucky first hour does not cry wolf.
BEHIND_MIN_SHARE = 0.25
#: An hour is judged only if usually at least this many people come in.
MIN_USUAL_VISITORS = 8
#: Slow hour: visitors at or under this share of usual...
QUIET_SHARE = 0.6
#: ...or, with enough visitors to tell, buying at under this share of usual.
CONVERSION_SHARE = 0.6
#: Busy hour: sales at least this multiple of a usual hour, and at least 5 bills.
BUSY_MULTIPLE = 1.5
#: News about an hour that ended longer ago than this (shop time) is stale --
#: found while catching up after downtime, say -- and skipped.
FRESH_HOURS = 2.0

#: Kinds sent only to chats that asked for hourly updates.
HOURLY = "hourly"


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


def _span(h: int) -> str:
    return f"{h}:00\u2013{h + 1}:00"


def hour_alert(hour: HourNow, key: str) -> Alert | None:
    """At most one message about a finished hour: slow, busy, or nothing."""
    if hour.usual_footfall < MIN_USUAL_VISITORS:
        return None                                  # usually quiet or closed
    problems = []
    if hour.footfall <= hour.usual_footfall * QUIET_SHARE:
        problems.append(
            f"Only {hour.footfall} people came in, against about "
            f"{round(hour.usual_footfall)} usually. Fewer are passing or stopping."
        )
    usual_rate = (hour.usual_transactions / hour.usual_footfall) if hour.usual_footfall else 0
    if hour.footfall >= MIN_USUAL_VISITORS and usual_rate > 0:
        rate = hour.transactions / hour.footfall
        if rate < usual_rate * CONVERSION_SHARE:
            problems.append(
                f"Only {rate:.0%} of the {hour.footfall} who came in bought, against "
                f"{usual_rate:.0%} usually. Worth checking the queue, stock or prices."
            )
    if problems:
        return Alert(
            "slow_hour", key,
            f"\u26a0\ufe0f Slow hour, {_span(hour.hour)}: {inr(hour.sales)} against about "
            f"{inr(hour.usual_sales)} usually.\n" + "\n".join(problems),
        )
    if (hour.usual_sales > 0 and hour.transactions >= 5
            and hour.sales >= hour.usual_sales * BUSY_MULTIPLE):
        return Alert(
            "busy_hour", key,
            f"\U0001f4c8 Busy hour, {_span(hour.hour)}: {inr(hour.sales)}, "
            f"{hour.sales / hour.usual_sales:.1f}\u00d7 a usual {hour.hour}:00. "
            f"{hour.transactions} bills from {hour.footfall} visitors. "
            "Keep the counter staffed and the shelves full.",
        )
    return None


def hourly_update(view: LiveView, hour: HourNow, totals: DayTotals) -> str:
    # Judged at the end of the hour this message is about, not at the last
    # hour the dashboard's pace had finished -- they can be an hour apart.
    point = view.band[hour.hour]
    by_then = point.actual if point.actual is not None else totals.sales
    day = f"Today by {hour.hour + 1}:00: {inr(by_then)}"
    if point.p50 > 0:
        diff = by_then / point.p50 - 1
        pct = round(abs(diff) * 100)
        usual = _singular(view.weekday)
        day += (f", about a usual {usual}." if pct < 5 else
                f", {pct}% {'ahead of' if diff > 0 else 'behind'} a usual {usual}.")
    else:
        day += "."
    return "\n".join([
        f"\U0001f550 {_span(hour.hour)}: {inr(hour.sales)} (usual {inr(hour.usual_sales)}), "
        f"{hour.transactions} bills from {hour.footfall} visitors.",
        day,
    ])


def _pace_line(view: LiveView) -> str | None:
    if view.pace is None or view.pace_through_hour is None:
        return None
    pct = round(abs(view.pace) * 100)
    by = f"by {view.pace_through_hour + 1}:00"
    usual = _singular(view.weekday)
    if pct < 5:
        return f"On your usual pace {by}."
    word = "ahead of" if view.pace > 0 else "behind"
    return f"{pct}% {word} a usual {usual} {by}."


def due_alerts(view: LiveView, day: date, now_hour: float,
               totals: DayTotals) -> list[Alert]:
    """Alerts that apply right now. The caller drops ones already sent."""
    out: list[Alert] = []
    d = day.isoformat()
    usual = _singular(view.weekday)

    # 1. The hour that just ended: slow, busy, and the optional update.
    hour = view.last_hour
    if hour is not None and 0 <= now_hour - (hour.hour + 1) <= FRESH_HOURS:
        key = f"{d}T{hour.hour:02d}"
        alert = hour_alert(hour, key)
        if alert:
            out.append(alert)
        if hour.usual_footfall > 0 or hour.footfall > 0:     # a trading hour
            out.append(Alert(HOURLY, key, hourly_update(view, hour, totals)))

    # 2. Well behind, or well ahead of, a usual day -- once there is enough of
    #    the day to judge. Each at most once a day.
    h = view.pace_through_hour
    if view.pace is not None and h is not None and view.typical_sales > 0:
        usual_by = view.band[h].p50
        so_far = view.band[h].actual or 0.0
        if usual_by / view.typical_sales >= BEHIND_MIN_SHARE:
            likely = (
                f" At this rate, about {inr(view.projected_sales)} by closing"
                f" against a usual {inr(view.typical_sales)}."
                if view.projected_sales is not None else ""
            )
            if view.pace <= BEHIND_PACE:
                out.append(Alert(
                    "behind_pace", d,
                    f"\U0001f4c9 Sales are {round(-view.pace * 100)}% behind a usual {usual}: "
                    f"{inr(so_far)} by {h + 1}:00, when you would normally have about "
                    f"{inr(usual_by)}.{likely}",
                ))
            elif view.pace >= AHEAD_PACE:
                out.append(Alert(
                    "ahead_pace", d,
                    f"\u2705 A strong day: {round(view.pace * 100)}% ahead of a usual {usual}, "
                    f"{inr(so_far)} by {h + 1}:00 against about {inr(usual_by)}.{likely}",
                ))

    # 3. The day's summary, once the usual closing time has passed.
    close = usual_close_hour(view)
    if close is not None and now_hour >= min(close, 23.99):  # open till midnight
        out.append(Alert("day_summary", d, day_summary(view, totals)))

    return out


def day_summary(view: LiveView, totals: DayTotals) -> str:
    usual = _singular(view.weekday)
    lines = [f"\U0001f9fe Today's close: {inr(totals.sales)}."]
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
    """The reply to /status: how today is going, in a few lines."""
    at = f"{clock.hour}:{clock.minute:02d}"
    if view is None or totals is None:
        return f"No sales recorded yet today (shop clock {at})."
    lines = [
        f"{inr(totals.sales)} sold by {at}: {totals.transactions} bills, "
        f"{totals.footfall} visitors."
    ]
    pace = _pace_line(view)
    if pace:
        lines.append(pace)
    if view.projected_sales is not None:
        lines.append(f"Likely {inr(view.projected_sales)} by closing.")
    hour = view.last_hour
    if hour is not None and (hour.footfall or hour.usual_footfall):
        lines.append(
            f"Last hour ({_span(hour.hour)}): {inr(hour.sales)} against about "
            f"{inr(hour.usual_sales)} usually."
        )
    return "\n".join(lines)
