"""Answers from the shop's own data, in words a shopkeeper uses.

Every figure comes from the same tables as the dashboard -- ``hourly_data``
for sales, bills and visitors, ``sale_line`` for products -- so the bot and
the dashboard never disagree. Comparisons are always like with like: today so
far against the same weekday *by the same time*, a week against the week
before it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

import pandas as pd
from sqlmodel import Session, select

from ...models import BundleSuggestion, HourlyData, Product, SaleLine, Store
from ..alerts.rules import inr, status_text
from ..insights import generate_insights
from ..live.today import today_view
from ..metrics import hourly_series
from . import parse as P

#: How far back "usual" looks.
USUAL_DAYS = 56
#: The window for "your busiest hour" and advice when no period is named.
TYPICAL_DAYS = 28
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

EXAMPLES = [
    "How much did I sell today?",
    "What sold most this week?",
    "How many people came in yesterday evening?",
    "How is today going?",
    "What is my busiest hour?",
    "How many Maggi did I sell today?",
    "How can I improve sales?",
]


# ---- the shop's data, loaded once per question ------------------------------------


@dataclass
class Shop:
    session: Session
    store: Store
    #: The shop clock (IST, naive): ahead of the real clock while fast-forwarding.
    clock: datetime
    _hourly: pd.DataFrame | None = None
    _lines: pd.DataFrame | None = None
    _products: dict[str, Product] | None = None
    _catalogue: list[P.CatalogueItem] | None = None

    @property
    def today(self) -> date:
        return self.clock.date()

    @property
    def clock_hour(self) -> float:
        return self.clock.hour + self.clock.minute / 60 + self.clock.second / 3600

    @property
    def products(self) -> dict[str, Product]:
        if self._products is None:
            rows = self.session.exec(select(Product).where(Product.store_id == self.store.id)).all()
            self._products = {p.sku: p for p in rows}
        return self._products

    @property
    def catalogue(self) -> list[P.CatalogueItem]:
        if self._catalogue is None:
            self._catalogue = P.build_catalogue(list(self.products.values()))
        return self._catalogue

    def name(self, sku: str) -> str:
        for item in self.catalogue:
            if item.sku == sku:
                return item.short
        return sku

    def hourly(self) -> pd.DataFrame:
        if self._hourly is None:
            since = (self.today - timedelta(days=400)).isoformat()
            rows = self.session.exec(
                select(HourlyData.date, HourlyData.hour, HourlyData.footfall,
                       HourlyData.transactions, HourlyData.sales)
                .where(HourlyData.store_id == self.store.id)
                .where(HourlyData.date >= since)
                .where(HourlyData.date <= self.today.isoformat())
            ).all()
            df = pd.DataFrame([dict(r._mapping) for r in rows],
                              columns=["date", "hour", "footfall", "transactions", "sales"])
            self._hourly = df.groupby(["date", "hour"], as_index=False)[
                ["footfall", "transactions", "sales"]].sum()
        return self._hourly

    def lines(self) -> pd.DataFrame:
        if self._lines is None:
            since = (self.today - timedelta(days=USUAL_DAYS + 35)).isoformat()
            rows = self.session.exec(
                select(SaleLine.date, SaleLine.hour, SaleLine.upload_id,
                       SaleLine.transaction_id, SaleLine.sku, SaleLine.qty, SaleLine.unit_price)
                .where(SaleLine.store_id == self.store.id)
                .where(SaleLine.date >= since)
                .where(SaleLine.date <= self.today.isoformat())
            ).all()
            df = pd.DataFrame([dict(r._mapping) for r in rows],
                              columns=["date", "hour", "upload_id", "transaction_id", "sku",
                                       "qty", "unit_price"])
            df["bill"] = df["upload_id"].astype(str) + ":" + df["transaction_id"].astype(str)
            df["revenue"] = df["qty"] * df["unit_price"]
            cost = {sku: p.cost_price for sku, p in self.products.items()}
            df["cost"] = df["qty"] * df["sku"].map(cost).fillna(0.0)
            self._lines = df
        return self._lines


# ---- windows of time ---------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    #: Keep only the part of ``end`` before this hour of the day (14.5 = 14:30),
    #: so a baseline day is cut at the same time as a half-finished today.
    cut: float | None = None


def _slice(df: pd.DataFrame, w: Window, hours: tuple[int, int] | None,
           numeric: list[str]) -> pd.DataFrame:
    d = df[(df["date"] >= w.start.isoformat()) & (df["date"] <= w.end.isoformat())]
    if hours:
        d = d[(d["hour"] >= hours[0]) & (d["hour"] < hours[1])]
    if w.cut is not None:
        last = d["date"] == w.end.isoformat()
        h0 = int(w.cut)
        d = d[~last | (d["hour"] <= h0)].copy()
        partial = (d["date"] == w.end.isoformat()) & (d["hour"] == h0)
        if partial.any():
            d[numeric] = d[numeric].astype(float)
            d.loc[partial, numeric] = d.loc[partial, numeric] * (w.cut - h0)
    return d


@dataclass
class Figures:
    sales: float = 0.0
    bills: float = 0.0
    visitors: float = 0.0

    @property
    def conversion(self) -> float:
        return self.bills / self.visitors if self.visitors else 0.0

    @property
    def avg_bill(self) -> float:
        return self.sales / self.bills if self.bills else 0.0


def figures(shop: Shop, w: Window, hours) -> Figures:
    d = _slice(shop.hourly(), w, hours, ["footfall", "transactions", "sales"])
    return Figures(float(d["sales"].sum()), float(d["transactions"].sum()),
                   float(d["footfall"].sum()))


def product_table(shop: Shop, w: Window, hours) -> pd.DataFrame:
    """Per SKU: qty, revenue, profit and bills in the window."""
    d = _slice(shop.lines(), w, hours, ["qty", "revenue", "cost"])
    if d.empty:
        return pd.DataFrame(columns=["qty", "revenue", "profit", "bills"])
    g = d.groupby("sku").agg(qty=("qty", "sum"), revenue=("revenue", "sum"),
                             cost=("cost", "sum"), bills=("bill", "nunique"))
    g["profit"] = g["revenue"] - g["cost"]
    return g


@dataclass
class Scope:
    """What a question is about in time, and what to compare it with."""
    window: Window
    label: str
    baseline: list[Window] = field(default_factory=list)
    baseline_label: str | None = None
    is_today: bool = False


def scope_for(shop: Shop, q: P.Query, default: str = "today") -> Scope:
    today = shop.today
    period = q.period
    if period is None:
        if default == "week":
            period = P.Period("range", today - timedelta(days=6), today, "the last 7 days",
                              "the 7 days before")
        elif default == "typical":
            period = P.Period("range", today - timedelta(days=TYPICAL_DAYS - 1), today,
                              f"the last {TYPICAL_DAYS // 7} weeks")
        else:
            period = P.Period("day", today, today, "today")

    includes_today = period.end >= today
    cut = shop.clock_hour if includes_today else None
    label = period.label
    if q.hours and includes_today and q.hours[1] <= shop.clock_hour:
        cut = None                      # that part of today is already over
    if period.kind == "day" and period.start == today:
        if cut is None:
            label = "today"
        elif q.hours:
            label = "today so far"
        else:
            label = f"today so far (till {shop.clock:%H:%M})"
    if q.hours_label:
        label = f"{label} {q.hours_label}"
    includes_today = cut is not None

    window = Window(period.start, min(period.end, today))
    scope = Scope(window, label, is_today=period.kind == "day" and period.start == today)

    if period.kind == "day":
        d = period.start
        present = set(shop.hourly()["date"])
        for k in range(1, USUAL_DAYS // 7 + 1):
            b = d - timedelta(weeks=k)
            if b.isoformat() in present:
                scope.baseline.append(Window(b, b, cut))
        scope.baseline_label = (f"a usual {WEEKDAYS[d.weekday()]}"
                                + (" by this time" if includes_today else ""))
    elif period.kind == "range":
        if period.label.startswith("this month"):
            start = (period.start - timedelta(days=1)).replace(day=1)
            end = start + (period.end - period.start)
            scope.baseline = [Window(start, end, cut)]
        elif period.label.startswith("last month"):
            end = period.start - timedelta(days=1)
            scope.baseline = [Window(end.replace(day=1), end)]
        else:
            n = (period.end - period.start).days + 1
            scope.baseline = [Window(period.start - timedelta(days=n),
                                     period.end - timedelta(days=n), cut)]
        scope.baseline_label = period.before_label
    return scope


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _versus(now: float, usual: float | None, label: str | None, money: bool = True,
            pct_points: bool = False) -> str | None:
    """"That's 12% above a usual Wednesday by this time (Rs 5,400)."""
    if usual is None or label is None or usual <= 0:
        return None
    shown = inr(usual) if money else (f"{usual:.0%}" if pct_points else f"{round(usual):,}")
    if pct_points:
        diff = (now - usual) * 100
        if abs(diff) < 2:
            return f"About the same as {label} ({shown})."
        return f"{abs(diff):.0f} points {'above' if diff > 0 else 'below'} {label} ({shown})."
    change = now / usual - 1
    if abs(change) < 0.03:
        return f"About the same as {label} ({shown})."
    return f"That's {abs(change):.0%} {'above' if change > 0 else 'below'} {label} ({shown})."


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _n(x: float) -> str:
    return f"{round(x):,}"


def _count(x: float, word: str) -> str:
    """"1 bill", "12 bills"."""
    return f"{_n(x)} {word}{'' if round(x) == 1 else 's'}"


def _not_yet(shop: Shop, q: P.Query, scope: Scope) -> str | None:
    if scope.is_today and q.hours and q.hours[0] > shop.clock_hour:
        return (f"{_cap(q.hours_label or 'that time')} hasn't come yet today "
                f"(shop clock {shop.clock:%H:%M}).")
    return None


# ---- one answer per kind of question ------------------------------------------------


def a_sales(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    wait = _not_yet(shop, q, s)
    if wait:
        return wait
    f = figures(shop, s.window, q.hours)
    if f.bills == 0:
        return f"Nothing sold {s.label}."
    base = _avg([figures(shop, w, q.hours).sales for w in s.baseline])
    items = float(product_table(shop, s.window, q.hours)["qty"].sum())
    things = f" ({_count(items, 'item')})" if items else ""
    lines = [f"{_cap(s.label)}: {inr(f.sales)} from {_count(f.bills, 'bill')}{things}."]
    vs = _versus(f.sales, base, s.baseline_label)
    if vs:
        lines.append(vs)
    return "\n".join(lines)


def a_compare(shop: Shop, q: P.Query) -> str:
    """Two periods side by side: "compare today with yesterday"."""
    a = scope_for(shop, q)
    older = P.Query(text=q.text, period=q.compare_to, hours=q.hours, hours_label=q.hours_label)
    b = scope_for(shop, older)
    wb, label_b = b.window, b.label
    if a.window.end >= shop.today and not (q.hours and q.hours[1] <= shop.clock_hour):
        # Like with like: the older period up to the same point.
        span = a.window.end - a.window.start
        wb = Window(b.window.start, b.window.start + span, shop.clock_hour)
        label_b = (f"{b.label} by the same time" if a.window.start == a.window.end
                   else f"{b.label} to the same day and time")
    fa, fb = figures(shop, a.window, q.hours), figures(shop, wb, q.hours)

    def line(label: str, f: Figures) -> str:
        return (f"{_cap(label)}: {inr(f.sales)} from {_count(f.bills, 'bill')}, "
                f"{_count(f.visitors, 'visitor')}, average bill {inr(f.avg_bill)}.")

    lines = [line(a.label, fa), line(label_b, fb)]
    if fb.sales > 0:
        change = fa.sales / fb.sales - 1
        lines.append("About the same sales." if abs(change) < 0.03 else
                     f"Sales are {abs(change):.0%} {'up' if change > 0 else 'down'} "
                     f"({'+' if change > 0 else '-'}{inr(abs(fa.sales - fb.sales))}).")
        if fb.visitors and fa.visitors:
            dv = fa.visitors / fb.visitors - 1
            dc = (fa.conversion - fb.conversion) * 100
            why = []
            if abs(dv) >= 0.05:
                why.append(f"{abs(dv):.0%} {'more' if dv > 0 else 'fewer'} people came in")
            if abs(dc) >= 3:
                why.append(f"{'more' if dc > 0 else 'fewer'} of them bought "
                           f"({fa.conversion:.0%} against {fb.conversion:.0%})")
            if why:
                lines.append(_cap(" and ".join(why)) + ".")
    return "\n".join(lines)


def a_visitors(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    wait = _not_yet(shop, q, s)
    if wait:
        return wait
    f = figures(shop, s.window, q.hours)
    if f.visitors == 0:
        return f"No visitors counted {s.label}."
    base = _avg([figures(shop, w, q.hours).visitors for w in s.baseline])
    lines = [f"{_cap(s.label)}: {_n(f.visitors)} people came in and {_n(f.bills)} bought "
             f"({f.conversion:.0%})."]
    if P._has(P.normalise(q.text), r"didnt buy|did not buy|without buying|not buy|no purchase|left"):
        lines.append(f"So about {_n(max(0.0, f.visitors - f.bills))} left without buying.")
    vs = _versus(f.visitors, base, s.baseline_label, money=False)
    if vs:
        lines.append(vs.replace("(", "(about ").replace(")", " people)"))
    return "\n".join(lines)


def a_bills(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    wait = _not_yet(shop, q, s)
    if wait:
        return wait
    f = figures(shop, s.window, q.hours)
    if f.bills == 0:
        return f"No bills {s.label}."
    base = _avg([figures(shop, w, q.hours).bills for w in s.baseline])
    lines = [f"{_cap(s.label)}: {_count(f.bills, 'bill')} from {_count(f.visitors, 'visitor')}, "
             f"{inr(f.sales)} in all."]
    vs = _versus(f.bills, base, s.baseline_label, money=False)
    if vs:
        lines.append(vs.replace("(", "(about ").replace(")", " bills)"))
    return "\n".join(lines)


def a_conversion(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    f = figures(shop, s.window, q.hours)
    if f.visitors == 0:
        return f"No visitors counted {s.label}, so no buying rate yet."
    rates = [figures(shop, w, q.hours) for w in s.baseline]
    base_f = Figures(sum(r.sales for r in rates), sum(r.bills for r in rates),
                     sum(r.visitors for r in rates))
    lines = [f"{_cap(s.label)}: {f.conversion:.0%} of visitors bought "
             f"({_n(f.bills)} of {_n(f.visitors)})."]
    vs = _versus(f.conversion, base_f.conversion if base_f.visitors else None,
                 s.baseline_label, money=False, pct_points=True)
    if vs:
        lines.append(vs)
    return "\n".join(lines)


def a_avg_bill(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    f = figures(shop, s.window, q.hours)
    if f.bills == 0:
        return f"No bills {s.label} yet."
    rates = [figures(shop, w, q.hours) for w in s.baseline]
    base = sum(r.sales for r in rates) / sum(r.bills for r in rates) \
        if rates and sum(r.bills for r in rates) else None
    lines = [f"{_cap(s.label)}: the average bill was {inr(f.avg_bill)} "
             f"({inr(f.sales)} over {_count(f.bills, 'bill')})."]
    vs = _versus(f.avg_bill, base, s.baseline_label)
    if vs:
        lines.append(vs)
    return "\n".join(lines)


def a_profit(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    t = product_table(shop, s.window, q.hours)
    if t.empty:
        return f"No sales {s.label}, so no profit yet."
    revenue, profit = float(t["revenue"].sum()), float(t["profit"].sum())
    base = _avg([float(product_table(shop, w, q.hours)["profit"].sum()) for w in s.baseline])
    lines = [f"{_cap(s.label)}: about {inr(profit)} gross profit on {inr(revenue)} of sales "
             f"({profit / revenue:.0%} margin)." if revenue else f"{_cap(s.label)}: no sales."]
    vs = _versus(profit, base, s.baseline_label)
    if vs:
        lines.append(vs)
    lines.append("That's what you sell for minus what you paid, before rent, wages and other costs.")
    return "\n".join(lines)


def a_top(shop: Shop, q: P.Query, lowest: bool = False) -> str:
    s = scope_for(shop, q, default="week" if lowest else "today")
    t = product_table(shop, s.window, q.hours)
    if lowest:
        all_skus = pd.Index(list(shop.products))
        t = t.reindex(all_skus.union(t.index), fill_value=0)
        zero = [shop.name(x) for x in t.index if t.loc[x, "qty"] == 0 and x in shop.products]
        some = t[t["qty"] > 0].sort_values(["qty", "revenue"])
        lines = [f"Slowest sellers {s.label}:"]
        if zero:
            shown = ", ".join(sorted(zero)[:8])
            more = f" and {len(zero) - 8} more" if len(zero) > 8 else ""
            lines.append(f"Didn't sell at all: {shown}{more}.")
        for sku, r in some.head(max(0, q.limit - (1 if zero else 0))).iterrows():
            lines.append(f"• {shop.name(sku)}: {_n(r['qty'])} sold ({inr(r['revenue'])})")
        if len(lines) == 1:
            return f"Nothing sold {s.label}."
        return "\n".join(lines)

    if t.empty:
        return f"Nothing sold {s.label}."
    key = {"qty": ["qty", "revenue"], "revenue": ["revenue", "qty"],
           "profit": ["profit", "revenue"]}[q.rank_by]
    top = t.sort_values(key, ascending=False).head(q.limit)
    what = {"qty": "Most sold", "revenue": "Biggest earners",
            "profit": "Most profitable"}[q.rank_by]
    lines = [f"{what} {s.label}:"]
    for i, (sku, r) in enumerate(top.iterrows(), 1):
        if q.rank_by == "profit":
            lines.append(f"{i}. {shop.name(sku)}: {inr(r['profit'])} profit on "
                         f"{_n(r['qty'])} sold")
        else:
            lines.append(f"{i}. {shop.name(sku)}: {_n(r['qty'])} sold, {inr(r['revenue'])}")
    return "\n".join(lines)


def a_product(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    t = product_table(shop, s.window, q.hours)
    skus = q.products[:5]
    base_tables = [product_table(shop, w, q.hours) for w in s.baseline]

    def one(sku: str) -> tuple[float, float, float, float | None]:
        qty = float(t.loc[sku, "qty"]) if sku in t.index else 0.0
        rev = float(t.loc[sku, "revenue"]) if sku in t.index else 0.0
        bills = float(t.loc[sku, "bills"]) if sku in t.index else 0.0
        base = _avg([float(b.loc[sku, "qty"]) if sku in b.index else 0.0 for b in base_tables]) \
            if base_tables else None
        return qty, rev, bills, base

    if len(skus) == 1:
        sku = skus[0]
        qty, rev, bills, base = one(sku)
        p = shop.products.get(sku)
        lines = [f"{shop.name(sku)} {s.label}: "
                 + (f"{_n(qty)} sold in {_count(bills, 'bill')}, {inr(rev)}." if qty else "none sold.")]
        if base is not None and s.baseline_label:
            lines.append(f"{_cap(s.baseline_label)}: about {base:.0f}."
                         if base >= 1 or qty else f"It rarely sells on {s.baseline_label[2:]} either.")
        if p:
            lines.append(f"Sells at {inr(p.sell_price)} each.")
        return "\n".join(lines)

    lines = [f"{_cap(s.label)}:"]
    total_q = total_r = 0.0
    for sku in skus:
        qty, rev, _, base = one(sku)
        total_q += qty
        total_r += rev
        usual = f" (usually about {base:.0f})" if base is not None else ""
        lines.append(f"• {shop.name(sku)}: {_n(qty)} sold, {inr(rev)}{usual}")
    lines.append(f"Together: {_n(total_q)} sold, {inr(total_r)}.")
    return "\n".join(lines)


def a_price(shop: Shop, q: P.Query) -> str:
    out = []
    for sku in q.products[:5]:
        p = shop.products.get(sku)
        if not p:
            continue
        margin = p.sell_price - p.cost_price
        pct = margin / p.sell_price if p.sell_price else 0
        out.append(f"{shop.name(sku)}: sells at {inr(p.sell_price)}, costs you "
                   f"{inr(p.cost_price)}, so you make {inr(margin)} each ({pct:.0%}).")
    return "\n".join(out) or "I couldn't find that product in your price list."


def _typical_hours(shop: Shop, q: P.Query) -> tuple[list[dict], str]:
    s = scope_for(shop, q, default="typical")
    d = _slice(shop.hourly(), s.window, None, ["footfall", "transactions", "sales"])
    if d.empty:
        return [], s.label
    days = d["date"].nunique()
    where = s.label if days == 1 else (f"on an average day over {s.label}"
                                       if q.period is None else f"on an average day {s.label}")
    return [h for h in hourly_series(d) if h["footfall"] > 0], where


def _span(h: int) -> str:
    return f"{h}:00–{h + 1}:00"


def a_peak_hour(shop: Shop, q: P.Query) -> str:
    hours, where = _typical_hours(shop, q)
    if not hours:
        return "No visitors recorded for that time yet."
    busy = max(hours, key=lambda h: h["footfall"])
    money = max(hours, key=lambda h: h["sales"])
    lines = [f"Busiest hour {where}: {_span(busy['hour'])}, about {busy['footfall']:.0f} people."]
    if money["hour"] != busy["hour"]:
        lines.append(f"The most money comes in at {_span(money['hour'])} "
                     f"(about {inr(money['sales'])}).")
    else:
        lines.append(f"It also brings the most money, about {inr(money['sales'])}.")
    lines.append("Keep the counter staffed and the best sellers stocked before then.")
    return "\n".join(lines)


def a_quiet_hour(shop: Shop, q: P.Query) -> str:
    hours, where = _typical_hours(shop, q)
    if not hours:
        return "No visitors recorded for that time yet."
    peak = max(h["footfall"] for h in hours)
    open_hours = [h for h in hours if h["footfall"] >= max(2.0, peak * 0.15)]
    quiet = min(open_hours, key=lambda h: h["footfall"])
    lines = [f"Quietest trading hour {where}: {_span(quiet['hour'])}, about "
             f"{quiet['footfall']:.0f} people and {inr(quiet['sales'])}."]
    enough = [h for h in open_hours if h["footfall"] >= peak * 0.3]
    if enough:
        worst = min(enough, key=lambda h: h["conversion"])
        lines.append(f"Fewest buyers for the crowd: {_span(worst['hour'])}, where "
                     f"{worst['conversion']:.0%} of visitors buy.")
    lines.append("A good time to restock, or to try a small offer that brings people in.")
    return "\n".join(lines)


def a_best_day(shop: Shop, q: P.Query) -> str:
    d = shop.hourly()
    since = (shop.today - timedelta(days=USUAL_DAYS)).isoformat()
    d = d[(d["date"] >= since) & (d["date"] < shop.today.isoformat())]
    if d.empty:
        return "Not enough history yet to compare days of the week."
    per_day = d.groupby("date")["sales"].sum().reset_index()
    per_day["dow"] = pd.to_datetime(per_day["date"]).dt.dayofweek
    by = per_day.groupby("dow")["sales"].mean()
    if len(by) < 2:
        return "Not enough history yet to compare days of the week."
    avg = float(by.mean())
    best, worst = int(by.idxmax()), int(by.idxmin())
    return "\n".join([
        f"Your best day is {WEEKDAYS[best]}: about {inr(by[best])} on average, "
        f"{by[best] / avg - 1:.0%} above a typical day.",
        f"The quietest is {WEEKDAYS[worst]}: about {inr(by[worst])}.",
        f"(Over the last {USUAL_DAYS // 7} weeks.)",
    ])


def a_status(shop: Shop, q: P.Query) -> str:
    view, totals = today_view(shop.session, shop.store, shop.clock)
    text = status_text(view, totals, shop.clock)
    t = product_table(shop, Window(shop.today, shop.today), None)
    if not t.empty:
        sku = t.sort_values(["qty", "revenue"], ascending=False).index[0]
        text += f"\nBest seller so far: {shop.name(sku)} ({_n(t.loc[sku, 'qty'])} sold)."
    return text


def a_summary(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    if s.is_today and not q.hours:
        return a_status(shop, q)
    f = figures(shop, s.window, q.hours)
    if f.bills == 0 and f.visitors == 0:
        return f"Nothing recorded {s.label}."
    base = _avg([figures(shop, w, q.hours).sales for w in s.baseline])
    lines = [
        f"{_cap(s.label)}: {inr(f.sales)} from {_count(f.bills, 'bill')}.",
        f"{_n(f.visitors)} people came in; {f.conversion:.0%} bought. "
        f"Average bill {inr(f.avg_bill)}.",
    ]
    vs = _versus(f.sales, base, s.baseline_label)
    if vs:
        lines.insert(1, vs)
    t = product_table(shop, s.window, q.hours)
    if not t.empty:
        sku = t.sort_values(["qty", "revenue"], ascending=False).index[0]
        lines.append(f"Best seller: {shop.name(sku)} ({_n(t.loc[sku, 'qty'])} sold).")
    return "\n".join(lines)


def a_bundles(shop: Shop, q: P.Query) -> str:
    rows = shop.session.exec(
        select(BundleSuggestion).where(BundleSuggestion.store_id == shop.store.id)
    ).all()
    if not rows:
        return ("No combo ideas yet. They come from your bills: open the Bundles page and "
                "work them out from your sales.")
    approved = [r for r in rows if r.status == "approved"]
    pending = sorted([r for r in rows if r.status == "pending"],
                     key=lambda r: -r.transactions_with_both)[:3]
    lines = []
    if approved:
        lines.append("Combos you approved:")
        lines += [f"• {shop.name(r.sku_a)} + {shop.name(r.sku_b)} at "
                  f"{inr(r.approved_price or r.suggested_price)}" for r in approved[:5]]
    if pending:
        lines.append("Often bought together:")
        lines += [f"• {shop.name(r.sku_a)} + {shop.name(r.sku_b)}: on "
                  f"{r.transactions_with_both} bills; as a combo {inr(r.suggested_price)} "
                  f"instead of {inr(r.separate_price)}" for r in pending]
        lines.append("Keep these side by side. Approve a combo on the Bundles page.")
    return "\n".join(lines) or "No combos waiting for you."


def a_stock(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q, default="week")
    t = product_table(shop, s.window, None)
    lines = ["I don't track stock levels yet, only what sells."]
    days = max(1, (s.window.end - s.window.start).days + 1)
    if q.products:
        for sku in q.products[:5]:
            qty = float(t.loc[sku, "qty"]) if sku in t.index else 0.0
            lines.append(f"{shop.name(sku)} sold {_n(qty)} over {s.label}, about "
                         f"{qty / days:.1f} a day. Keep at least a few days of that on the shelf.")
        return "\n".join(lines)
    if not t.empty:
        lines.append(f"Fastest sellers over {s.label}, keep these topped up:")
        for sku, r in t.sort_values("qty", ascending=False).head(q.limit).iterrows():
            lines.append(f"• {shop.name(sku)}: about {r['qty'] / days:.0f} a day")
    return "\n".join(lines)


def a_big_bill(shop: Shop, q: P.Query) -> str:
    s = scope_for(shop, q)
    d = _slice(shop.lines(), s.window, q.hours, ["qty", "revenue", "cost"])
    if d.empty:
        return f"No bills {s.label}."
    bills = d.groupby("bill").agg(total=("revenue", "sum"), items=("qty", "sum"),
                                  hour=("hour", "first"))
    biggest = bills["total"].idxmax()
    top = bills.loc[biggest]
    what = d[d["bill"] == biggest]
    names = ", ".join(f"{int(r.qty)}× {shop.name(r.sku)}" for r in what.itertuples())
    return (f"Biggest bill {s.label}: {inr(top['total'])} at {int(top['hour'])}:00, "
            f"{_count(top['items'], 'item')} ({names}).\n"
            f"The average bill was {inr(bills['total'].mean())}.")


def a_offer(shop: Shop, q: P.Query) -> str:
    """When an offer would help most: the quiet day and the quiet hours."""
    d = shop.hourly()
    since = (shop.today - timedelta(days=USUAL_DAYS)).isoformat()
    d = d[(d["date"] >= since) & (d["date"] < shop.today.isoformat())]
    if d.empty:
        return "I need a few weeks of sales before I can say when an offer would help."
    per_day = d.groupby("date")["sales"].sum().reset_index()
    per_day["dow"] = pd.to_datetime(per_day["date"]).dt.dayofweek
    by = per_day.groupby("dow")["sales"].mean()
    worst = int(by.idxmin())
    hours = [h for h in hourly_series(d) if h["footfall"] > 0]
    peak = max(h["footfall"] for h in hours)
    open_hours = [h for h in hours if h["footfall"] >= max(2.0, peak * 0.15)]
    quiet = sorted(sorted(open_hours, key=lambda h: h["footfall"])[:2], key=lambda h: h["hour"])
    lines = [
        "Run it when the shop is quiet, so it brings in people who wouldn't have come anyway:",
        f"• Day: {WEEKDAYS[worst]}, about {inr(by[worst])} against {inr(by.mean())} "
        "on a typical day.",
        "• Hours: " + " and ".join(_span(h["hour"]) for h in quiet) + ".",
        "Avoid your busy hours: people buy then anyway, and the discount is money lost.",
    ]
    pair = shop.session.exec(
        select(BundleSuggestion)
        .where(BundleSuggestion.store_id == shop.store.id)
        .where(BundleSuggestion.status != "rejected")
        .order_by(BundleSuggestion.transactions_with_both.desc())
    ).first()
    if pair is not None:
        lines.append(f"A pairing people already like: {shop.name(pair.sku_a)} + "
                     f"{shop.name(pair.sku_b)}.")
    return "\n".join(lines)


def a_opening(shop: Shop, q: P.Query) -> str:
    """Whether people are already there at opening, or still coming at closing."""
    window = Window(shop.today - timedelta(days=TYPICAL_DAYS), shop.today - timedelta(days=1))
    d = _slice(shop.hourly(), window, None, ["footfall", "transactions", "sales"])
    hours = [h for h in hourly_series(d) if h["footfall"] > 0] if not d.empty else []
    if not hours:
        return "I need a few weeks of sales before I can say anything about your hours."
    avg = sum(h["footfall"] for h in hours) / len(hours)
    first, last = hours[0], hours[-1]
    return "\n".join([
        f"You usually trade from {first['hour']}:00 to {last['hour'] + 1}:00.",
        f"The first hour brings about {first['footfall']:.0f} people, "
        + ("a busy start: people may be waiting, so opening a little earlier could catch them."
           if first["footfall"] >= avg * 0.8 else
           "a slow start, so opening earlier probably won't pay."),
        f"The last hour brings about {last['footfall']:.0f} people, "
        + ("still busy: staying open a little later could pay."
           if last["footfall"] >= avg * 0.8 else
           "a quiet end, so closing later probably won't pay."),
    ])


# ---- advice ------------------------------------------------------------------------


def advice(shop: Shop) -> list[str]:
    tips: list[str] = []
    today = shop.today

    # 1. Today, if there is something to act on right now.
    view, _ = today_view(shop.session, shop.store, shop.clock)
    if view is not None and view.pace is not None and view.pace_through_hour is not None:
        h = view.pace_through_hour
        usual_by = view.band[h].p50
        left = (view.typical_sales - usual_by) / view.typical_sales if view.typical_sales else 0
        if view.pace <= -0.10 and left >= 0.15:
            tips.append(
                f"Today is {abs(view.pace):.0%} behind a usual {view.weekday[:-1]}, but about "
                f"{left:.0%} of a usual day's sales are still to come. Make sure the counter is "
                "staffed and the best sellers are full and in view for the rest of the day.")
        elif view.pace >= 0.10:
            tips.append(
                f"Today is {view.pace:.0%} ahead of a usual {view.weekday[:-1]}. Check the best "
                "sellers now so a good day doesn't end with empty shelves.")

    # 2. Patterns from the last four weeks, the same ones the dashboard shows.
    window = Window(today - timedelta(days=TYPICAL_DAYS - 1), today)
    d = _slice(shop.hourly(), window, None, ["footfall", "transactions", "sales"])
    if not d.empty:
        found = generate_insights(d.assign(store_id=shop.store.code), today.isoformat())
        for kind in ("warning", "opportunity"):
            tips += [i["text"] for i in found if i["kind"] == kind]

    t = product_table(shop, Window(today - timedelta(days=6), today), None)

    # 3. Things bought together: place them side by side.
    pair = shop.session.exec(
        select(BundleSuggestion)
        .where(BundleSuggestion.store_id == shop.store.id)
        .where(BundleSuggestion.status != "rejected")
        .order_by(BundleSuggestion.transactions_with_both.desc())
    ).first()
    if pair is not None:
        tips.append(
            f"Customers often buy {shop.name(pair.sku_a)} with {shop.name(pair.sku_b)} "
            f"({pair.transactions_with_both} bills recently). Keep them side by side, "
            "or try them as a combo on the Bundles page.")

    # 4. The best seller must never run out.
    if not t.empty:
        sku = t.sort_values("qty", ascending=False).index[0]
        tips.append(
            f"{shop.name(sku)} is your best seller, about {t.loc[sku, 'qty'] / 7:.0f} a day "
            "this week. Never let it run out, and keep it where people see it first.")

    # 5. A good-margin product that could sell more.
    if not t.empty and shop.products:
        margins = {sku: (p.sell_price - p.cost_price) / p.sell_price
                   for sku, p in shop.products.items() if p.sell_price}
        med_qty = float(t["qty"].median())
        candidates = [(margins[sku], sku) for sku in t.index
                      if sku in margins and 0 < t.loc[sku, "qty"] < med_qty]
        if candidates:
            m, sku = max(candidates)
            if m >= sorted(margins.values())[len(margins) * 3 // 4]:
                tips.append(
                    f"{shop.name(sku)} earns you {m:.0%} on every sale, more than most, but sold "
                    f"only {_n(t.loc[sku, 'qty'])} this week. Put it near the counter or "
                    "suggest it at billing.")

    seen, out = set(), []
    for tip in tips:
        if tip not in seen:
            seen.add(tip)
            out.append(tip)
    return out[:5]


def a_advice(shop: Shop, q: P.Query) -> str:
    tips = advice(shop)
    if not tips:
        return "I need a few days of sales before I can suggest anything useful."
    lines = ["Here's what your numbers suggest:"]
    lines += [f"{i}. {tip}" for i, tip in enumerate(tips, 1)]
    lines.append("Ask me about any of these, like \"busiest hour\" or \"combos\".")
    return "\n".join(lines)


# ---- conversation --------------------------------------------------------------------


def examples(k: int = 5) -> str:
    return "\n".join(f"• {e}" for e in EXAMPLES[:k])


def a_greeting(shop: Shop, q: P.Query) -> str:
    return (f"Namaste! I can answer questions about {shop.store.code} "
            f"· {shop.store.name or 'your shop'} in your own words. For example:\n"
            + examples())


def a_help(shop: Shop, q: P.Query) -> str:
    return ("Ask me in your own words, no commands needed. I know your sales, bills, "
            "visitors, products, prices, profit, busy and quiet hours, and combos. Try:\n"
            + examples(len(EXAMPLES))
            + "\n\nSay \"hourly updates on\" for a message after every hour.")


def a_thanks(shop: Shop, q: P.Query) -> str:
    return "Happy to help. Ask me anything about the shop's sales."


def a_unknown(shop: Shop, q: P.Query) -> str:
    return ("Sorry, I didn't catch that. I can answer questions about your shop's sales, "
            "customers and products, like:\n" + examples(4))


def a_stop(shop: Shop, q: P.Query) -> str:
    return "To stop alerts in this chat, send /stop. You can connect again any time."


HANDLERS: dict[str, Callable[[Shop, P.Query], str]] = {
    P.SUMMARY: a_summary, P.SALES: a_sales, P.BILLS: a_bills, P.VISITORS: a_visitors,
    P.CONVERSION: a_conversion, P.AVG_BILL: a_avg_bill, P.PROFIT: a_profit,
    P.TOP: a_top, P.BOTTOM: lambda s, q: a_top(s, q, lowest=True),
    P.PRODUCT: a_product, P.PRICE: a_price, P.PEAK_HOUR: a_peak_hour,
    P.QUIET_HOUR: a_quiet_hour, P.BEST_DAY: a_best_day, P.STATUS: a_status,
    P.ADVICE: a_advice, P.BUNDLES: a_bundles, P.STOCK: a_stock,
    P.GREETING: a_greeting, P.HELP: a_help, P.THANKS: a_thanks,
    P.STOP_ALERTS: a_stop, P.UNKNOWN: a_unknown, P.COMPARE: a_compare,
    P.OFFER: a_offer, P.OPENING: a_opening, P.BIG_BILL: a_big_bill,
}

#: Pleasantries are dropped when the same message also asks something real.
_SMALL_TALK = {P.GREETING, P.THANKS}


def answer(session: Session, store: Store, text: str, clock: datetime,
           set_hourly: Callable[[bool], str] | None = None) -> str:
    """The reply to one message. ``set_hourly`` switches this chat's hourly
    updates; without it (the web page) the reply says where to do that."""
    shop = Shop(session, store, clock)
    q = P.parse(text, shop.today, shop.catalogue)
    intents = [i for i in q.intents if i not in _SMALL_TALK] or q.intents
    replies = []
    for intent in intents[:3]:
        if intent in (P.HOURLY_ON, P.HOURLY_OFF):
            replies.append(set_hourly(intent == P.HOURLY_ON) if set_hourly else
                           "Hourly updates are set per Telegram chat: tick them on the "
                           "Phone alerts page, or tell the bot \"hourly updates on\".")
            continue
        replies.append(HANDLERS[intent](shop, q))
    return "\n\n".join(r for r in replies if r)
