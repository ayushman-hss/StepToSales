"""What stands out, in words an owner can act on.

Every insight here has to pass three tests before it is shown:

* it is about money or about a decision the owner can make -- "18:00 sells
  worse than the rest of your day, about Rs 640 a day" rather than "18:00
  converts at 15.2%";
* it is not noise -- hour-level claims need enough visitors, and a gap in the
  buying rate must be well beyond what chance would give with that many;
* it never contradicts the dashboard headline -- the buying rate quoted is
  always the headline's (all bills over all visitors).

Ordered by what matters most: how the period went against the one before,
then the biggest leak in money, then patterns to plan around.
"""
from __future__ import annotations

import math
from typing import Dict, List

import pandas as pd

from .alerts.rules import inr
from .metrics import complete_days, compute_kpis, hourly_series

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

#: At most this many cards; more and nobody reads them.
MAX_INSIGHTS = 4
#: A change smaller than this is "about the same".
CHANGE_NOISE = 0.05
#: The earlier period needs this many visitors to compare with, and a gap in
#: the buying rate must be this many standard errors wide to be reported.
MIN_VISITORS = 30
MIN_Z = 2.0
#: A leak smaller than this share of a day's takings is not worth a card.
MIN_LEAK_SHARE = 0.02
#: Days needed before the shop's rush hours are named.
MIN_RUSH_DAYS = 3
#: Bills needed in a part of the day before its average bill is quoted.
MIN_PART_BILLS = 30
#: Each weekday must occur this often before one is called "the quiet day".
MIN_WEEKDAY_DAYS = 2

PARTS = [("Morning", 0, 12), ("Afternoon", 12, 17), ("Evening", 17, 24)]


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _hour(h: int) -> str:
    return f"{h}:00"


def _totals(df: pd.DataFrame) -> Dict[str, float]:
    ff, tx, sales = (float(df[c].sum()) for c in ("footfall", "transactions", "sales"))
    return {
        "footfall": ff,
        "bills": tx,
        "sales": sales,
        "rate": tx / ff if ff else 0.0,
        "basket": sales / tx if tx else 0.0,
    }


# ---------------------------------------------------------------------------
# 1. how this period went against the one before, and why
# ---------------------------------------------------------------------------

def _versus_before(now: pd.DataFrame, before: pd.DataFrame, label: str) -> Dict | None:
    a, b = _totals(now), _totals(before)
    if b["sales"] <= 0 or b["footfall"] < MIN_VISITORS or a["sales"] <= 0:
        return None
    change = a["sales"] / b["sales"] - 1
    # With few bills, takings swing a lot from one day to the next by chance
    # alone (roughly 1/sqrt(bills)); a smaller change than that is not news.
    bills = min(a["bills"], b["bills"])
    noise = max(CHANGE_NOISE, 1.5 / math.sqrt(bills)) if bills else 1.0
    if abs(change) < noise:
        return {
            "kind": "observation",
            "text": (
                f"Takings are about the same as {label}: {inr(a['sales'])} against "
                f"{inr(b['sales'])}"
                + (", within a normal day's ups and downs." if noise > CHANGE_NOISE else ".")
            ),
        }

    # Sales = visitors x share who buy x average bill, so the change splits
    # exactly into those three (on a log scale). Name the one that moved most.
    parts = {
        "visitors": math.log(a["footfall"] / b["footfall"]) if b["footfall"] and a["footfall"] else 0.0,
        "buyers": math.log(a["rate"] / b["rate"]) if b["rate"] and a["rate"] else 0.0,
        "bill": math.log(a["basket"] / b["basket"]) if b["basket"] and a["basket"] else 0.0,
    }
    main = max(parts, key=lambda k: abs(parts[k]))
    up = change > 0
    direction = "up" if up else "down"
    head = (
        f"Takings are {direction} {_pct(abs(change))} on {label} "
        f"({inr(a['sales'])} against {inr(b['sales'])})."
    )
    more = parts[main] > 0
    if main == "visitors":
        why = (f"Mostly {'more' if more else 'fewer'} people came in "
               f"({a['footfall']:,.0f} visitors against {b['footfall']:,.0f}).")
        fix = "The drop is at the door, not at the counter."
    elif main == "buyers":
        why = (f"Mostly a {'larger' if more else 'smaller'} share of visitors bought: "
               f"{_pct(a['rate'])} against {_pct(b['rate'])}.")
        fix = "Check for empty shelves, prices or a slow counter."
    else:
        why = (f"Mostly the size of the average bill: {inr(a['basket'])} against "
               f"{inr(b['basket'])}.")
        fix = "Fewer or cheaper items per bill: check what ran out of stock."
    if all(abs(v) < CHANGE_NOISE for k, v in parts.items() if k != main):
        why += " The rest barely moved."
    if not up:
        why += f" {fix}"
    return {"kind": "win" if up else "warning", "text": f"{head} {why}"}


# ---------------------------------------------------------------------------
# 2. the rush: when it comes, and the buyers it loses
# ---------------------------------------------------------------------------

def _busy_hours(df: pd.DataFrame) -> List[int]:
    """Hours well above the shop's typical hour: its rush, however many."""
    hourly = [h for h in hourly_series(df) if h["footfall"] > 0]
    if len(hourly) < 6:
        return []
    typical = float(pd.Series([h["footfall"] for h in hourly]).median())
    return [h["hour"] for h in hourly if h["footfall"] >= 1.5 * typical]


def _spans(hours: List[int]) -> List[tuple[int, int]]:
    """[7, 8, 9, 18, 19] -> [(7, 10), (18, 20)]: runs of hours, end exclusive."""
    out: List[tuple[int, int]] = []
    for h in sorted(hours):
        if out and out[-1][1] == h:
            out[-1] = (out[-1][0], h + 1)
        else:
            out.append((h, h + 1))
    return out


def _span_text(spans: List[tuple[int, int]]) -> str:
    parts = [f"{_hour(a)}–{_hour(b)}" for a, b in spans]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _rush(df: pd.DataFrame, week: bool, usual: bool = False) -> Dict | None:
    days = int(df["date"].nunique())
    if days < MIN_RUSH_DAYS:
        return None                    # one day's busy hours are mostly chance
    busy = _busy_hours(df)
    if not busy:
        return None
    # At most the two biggest rushes; a stray busy hour is not a rush.
    visitors = df.groupby("hour")["footfall"].sum()
    spans = sorted(_spans(busy), key=lambda sp: -sum(visitors.get(h, 0) for h in range(*sp)))[:2]
    spans.sort()
    busy = [h for a, b in spans for h in range(a, b)]
    in_rush = df[df["hour"].isin(busy)]
    calm = df[~df["hour"].isin(busy)]
    r, c, all_ = _totals(in_rush), _totals(calm), _totals(df)
    share = r["footfall"] / all_["footfall"]
    when = (
        f"Your rush is {_span_text(spans)}" if len(spans) == 1
        else f"Your rushes are {_span_text(spans)}"
    )
    if usual:                          # judged from recent weeks, not this day
        when = "On a usual day, y" + when[1:]
    head = f"{when}: {_pct(share)} of your visitors come in those {len(busy)} hours."

    # Do people in the rush buy less often than in calmer hours? A two-sample
    # test on the buying rate, so a gap that chance explains is not reported.
    gap = c["rate"] - r["rate"]
    pooled = all_["rate"]
    se = math.sqrt(pooled * (1 - pooled) * (1 / r["footfall"] + 1 / c["footfall"])) \
        if r["footfall"] and c["footfall"] and 0 < pooled < 1 else 0.0
    if se and gap >= 0.03 and gap / se >= MIN_Z:
        # Some of the gap is people in a hurry; claim only a quarter of it.
        won_back = 0.25 * gap * r["footfall"] / days * r["basket"]
        if won_back >= MIN_LEAK_SHARE * all_["sales"] / days:
            gain = f"about {inr(won_back)} a day" + (f" ({inr(won_back * 7)} a week)" if week else "")
            return {
                "kind": "warning",
                "text": (
                    f"{head} But only {_pct(r['rate'])} of them buy, against "
                    f"{_pct(c['rate'])} in calmer hours, a sign that people leave rather "
                    "than wait. Winning back a quarter of that gap, with a second person "
                    "at the counter or a UPI code by the door, is worth "
                    f"{gain}."
                ),
            }
    starts = " and ".join(_hour(a) for a, _ in spans)
    return {
        "kind": "observation",
        "text": f"{head} Restock and be at the counter before {starts}.",
    }


# ---------------------------------------------------------------------------
# 3. a quiet weekday, and whether it is the door or the counter
# ---------------------------------------------------------------------------

def _quiet_weekday(df: pd.DataFrame, partial_date: str | None) -> Dict | None:
    full = complete_days(df, partial_date)
    per_day = full.groupby("date", as_index=False)[["footfall", "transactions", "sales"]].sum()
    if per_day.empty:
        return None
    per_day["dow"] = pd.to_datetime(per_day["date"]).dt.dayofweek
    counts = per_day.groupby("dow")["date"].count()
    if len(counts) < 7 or counts.min() < MIN_WEEKDAY_DAYS:
        return None                       # not every weekday seen often enough
    by = per_day.groupby("dow")[["footfall", "transactions", "sales"]].mean()
    quiet = int(by["sales"].idxmin())
    q = by.loc[quiet]
    rest = by.drop(index=quiet).mean()    # the other six days
    if rest["sales"] <= 0 or q["sales"] >= rest["sales"] * 0.85 or q["footfall"] <= 0:
        return None
    day = DAY_NAMES[quiet]
    gap = float(rest["sales"] - q["sales"])
    head = (
        f"{day}s bring in {inr(q['sales'])}, {inr(gap)} less than your other days "
        f"({_pct(gap / rest['sales'])} lower)."
    )
    # Which of visitors, buying rate or bill size makes up most of the gap?
    q_rate, o_rate = q["transactions"] / q["footfall"], rest["transactions"] / rest["footfall"]
    door = abs(math.log(q["footfall"] / rest["footfall"]))
    counter = abs(math.log(q_rate / o_rate)) if q_rate and o_rate else 0.0
    if door >= counter:
        why = (
            f"Mostly fewer people come in ({q['footfall']:,.0f} visitors against "
            f"{rest['footfall']:,.0f}). An offer only helps if it brings them through "
            f"the door; if {day}s are always this quiet, shorter hours may cost you less."
        )
        return {"kind": "observation", "text": f"{head} {why}"}
    why = (
        f"People do come, but only {_pct(q_rate)} buy against {_pct(o_rate)} on "
        f"other days. Check stock and staffing on {day}s."
    )
    return {"kind": "warning", "text": f"{head} {why}"}


# ---------------------------------------------------------------------------
# 4. different customers at different times
# ---------------------------------------------------------------------------

def _bill_by_time(df: pd.DataFrame) -> Dict | None:
    parts = []
    for name, start, end in PARTS:
        part = df[(df["hour"] >= start) & (df["hour"] < end)]
        bills = float(part["transactions"].sum())
        if bills >= MIN_PART_BILLS:
            parts.append((name, float(part["sales"].sum()) / bills))
    if len(parts) < 2:
        return None
    high = max(parts, key=lambda p: p[1])
    low = min(parts, key=lambda p: p[1])
    ratio = high[1] / low[1] if low[1] else 0
    if ratio < 1.4:
        return None
    if ratio >= 2.5:
        compare = f"{ratio:.1f} times the {inr(low[1])} of"
    elif ratio >= 1.8:
        compare = f"almost twice the {inr(low[1])} of"
    else:
        compare = f"against {inr(low[1])} for"
    return {
        "kind": "opportunity",
        "text": (
            f"{high[0]} bills average {inr(high[1])}, {compare} "
            f"{low[0].lower()} bills. Keep the bigger items {high[0].lower()} shoppers "
            f"buy in stock and in sight then; {low[0].lower()}s are for quick buys "
            "near the counter."
        ),
    }


# ---------------------------------------------------------------------------

def generate_insights(
    df: pd.DataFrame,
    partial_date: str | None = None,
    previous: pd.DataFrame | None = None,
    previous_label: str = "the period before",
    history: pd.DataFrame | None = None,
) -> List[Dict[str, str]]:
    """Returns a list of {kind, text}; kind is warning | opportunity | observation | win.

    ``previous`` is the same span just before (or, for one day, the same
    weekday a week earlier up to the same hour); without it, the comparison
    card is left out. ``history`` is recent complete days, used for patterns
    one day is too short to show (when the rush comes).
    """
    if df.empty or float(df["footfall"].sum()) <= 0:
        return []
    full_days = int(complete_days(df, partial_date)["date"].nunique())

    found = [
        _versus_before(df, previous, previous_label) if previous is not None and not previous.empty else None,
        _rush(df, week=full_days >= 7) or (
            _rush(history, week=True, usual=True) if history is not None and not history.empty else None
        ),
        _quiet_weekday(df, partial_date),
        _bill_by_time(df),
    ]
    return [f for f in found if f][:MAX_INSIGHTS]


def whatsapp_summary(
    df: pd.DataFrame,
    title: str = "Summary",
    partial_date: str | None = None,
    insights: List[Dict[str, str]] | None = None,
) -> str:
    """The day in a message to forward. ``insights`` are the dashboard's own,
    so the message and the page never disagree; worked out here if not given."""
    k = compute_kpis(df)
    hourly = hourly_series(df)
    non_empty = [h for h in hourly if h["footfall"] > 0]
    peak = max(non_empty, key=lambda h: h["footfall"]) if non_empty else None

    lines = [
        f"📊 *{title}*",
        "",
        f"👣 Footfall: {k['total_footfall']:,}",
        f"💰 Sales: {inr(k['total_sales'])}",
        f"🎯 Conversion: {k['conversion_rate']*100:.1f}%",
        f"🛒 Avg basket: {inr(k['avg_basket'])}",
    ]
    if peak:
        days = int(df["date"].nunique())
        note = "" if days == 1 else " a day"
        lines.append(f"⏰ Busiest: {peak['hour']}:00 ({round(peak['footfall']):,} visitors{note})")

    if insights is None:
        insights = generate_insights(df, partial_date)
    top = insights[:2]
    if top:
        lines.append("")
        for i in top:
            prefix = {"warning": "⚠️", "opportunity": "💡", "win": "✅", "observation": "ℹ️"}.get(i["kind"], "•")
            lines.append(f"{prefix} {i['text']}")

    return "\n".join(lines)
