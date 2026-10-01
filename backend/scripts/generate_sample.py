"""Build the hourly footfall file from the per-store sale lines.

Transactions and sales are *derived* from the sale lines, which are the record
of what actually sold, so the dashboard and the bundle engine can never
disagree. Only footfall is modelled, because footfall is the one number a POS
genuinely cannot tell you -- it needs a door counter. Each store has its own
conversion profile, so the two look like different businesses because they are.

Run after generate_bundle_sample.py (reset_demo.py runs both, in order, with
one shared clock so today stops at the same minute in both files).

    cd backend && python scripts/generate_sample.py
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
STORES = ["S1", "S2"]

PROFILES = {
    # A neighbourhood kirana: people arrive intending to buy, so most of them
    # do. Conversion dips at the peaks because queues put some people off.
    "S1": {
        "open_hours": range(8, 22),
        "peak_hours": {9, 10, 11, 18, 19, 20},
        "conversion_peak": (0.52, 0.62),
        "conversion_offpeak": (0.64, 0.78),
        "idle_footfall": (0, 3),
    },
    # A kiosk by the station: enormous passing trade, most of which walks
    # straight past the counter. High footfall, low conversion.
    "S2": {
        "open_hours": range(6, 23),
        "peak_hours": {7, 8, 9, 18, 19, 20, 21},
        "conversion_peak": (0.24, 0.34),
        "conversion_offpeak": (0.36, 0.50),
        "idle_footfall": (1, 6),
    },
}


def build(store: str, now: datetime) -> list[dict]:
    lines = pd.read_excel(BASE / f"sales_lines_{store}.xlsx")
    lines["date"] = pd.to_datetime(lines["date"]).dt.strftime("%Y-%m-%d")
    lines["value"] = lines["qty"] * lines["unit_price"]

    sold = (
        lines.groupby(["date", "hour"])
        .agg(transactions=("transaction_id", "nunique"), sales=("value", "sum"))
        .to_dict("index")
    )

    profile = PROFILES[store]
    today = now.date()
    elapsed = now.minute / 60
    rows: list[dict] = []

    # Walk every calendar day, not just days that happen to have sales, so a
    # quiet morning still shows up as visitors who did not buy.
    day = date.fromisoformat(lines["date"].min())
    while day <= today:
        key_day = day.isoformat()
        for hour in profile["open_hours"]:
            if day == today and hour > now.hour:
                break  # the rest of today has not happened yet

            actual = sold.get((key_day, hour))
            transactions = int(actual["transactions"]) if actual else 0
            sales = float(actual["sales"]) if actual else 0.0

            if transactions:
                lo, hi = (
                    profile["conversion_peak"]
                    if hour in profile["peak_hours"]
                    else profile["conversion_offpeak"]
                )
                footfall = max(transactions, round(transactions / random.uniform(lo, hi)))
            else:
                footfall = random.randint(*profile["idle_footfall"])  # NOSONAR -- seeded simulation
                if day == today and hour == now.hour:
                    footfall = round(footfall * elapsed)

            rows.append({
                "date": key_day,
                "hour": hour,
                "footfall": footfall,
                "transactions": transactions,
                "sales": round(sales, 2),
                "store_id": store,
            })
        day += timedelta(days=1)
    return rows


def main(now: datetime | None = None) -> None:
    now = now or datetime.now(IST)
    random.seed(7)
    rows: list[dict] = []
    for store in STORES:
        store_rows = build(store, now)
        rows.extend(store_rows)
        ff = sum(r["footfall"] for r in store_rows)
        tx = sum(r["transactions"] for r in store_rows)
        sales = sum(r["sales"] for r in store_rows)
        days = len({r["date"] for r in store_rows})
        print(
            f"  {store}: {days} days, {ff:,} visitors, {tx:,} bills, Rs{sales:,.0f}, "
            f"{tx / ff * 100:.1f}% bought, Rs{sales / tx:.0f} per bill"
        )
    pd.DataFrame(rows).to_excel(BASE / "sample-data.xlsx", index=False)
    print(f"  wrote sample-data.xlsx ({len(rows):,} hourly rows, up to {now:%H:%M} today)")


if __name__ == "__main__":
    main()
