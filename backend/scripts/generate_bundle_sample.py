"""Generate per-store sale lines (one row per item on a bill).

The history always ends *now*: twelve full weeks up to yesterday, plus today
up to the current hour in India Standard Time. Run it before a demo and the
dashboard's "today" is actually today.

Patterns layered onto every bill, each one a known feature of Indian
neighbourhood retail rather than noise:

* time of day   -- trade all day, heavier at each shop's own peaks
* day of week   -- the kirana fills up at the weekend, the station kiosk
                   empties out when nobody commutes
* month cycle   -- the first days after salaries land bring a monthly
                   stock-up at the kirana: more bills and more rice and oil
                   bought two at a time
* day to day    -- no two days are alike even with the same weekday
* price         -- cheap everyday goods sell many times a day, expensive
                   ones rarely: purchase frequency falls with price, so a
                   perfume cannot out-earn the rice
* format        -- each shop sells like what it is: the kirana leans on
                   staples and dairy, the station kiosk on snacks, drinks
                   and biscuits, and almost never sells rice or detergent
* affinities    -- a few specific products are bought together far more
                   than chance (this biscuit with that tea), with a long
                   tail of weak pairings behind them. That skew is what
                   real basket data looks like, and what bundling relies on.

Deliberately NOT modelled here yet: weather and festivals (planned as their
own step, from real Open-Meteo history and the official holiday list).

    cd backend && python scripts/generate_bundle_sample.py
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]

# India has one time zone and no daylight saving, so a fixed offset is exact
# and avoids depending on the OS time zone database (absent on Windows).
IST = timezone(timedelta(hours=5, minutes=30))
WEEKS = 12

# Share of two-item bills that are one of the shop's signature pairings; the
# rest are random pairs within the category rules.
SIGNATURE_SHARE = 0.15
SIGNATURE_PAIRS = 6

# How strongly purchase frequency falls with price: weight = price ** -e.
# Necessities barely respond -- a family buys rice every week whatever it
# costs -- while discretionary goods respond strongly, so a Rs4,000 perfume
# sells rarely instead of out-earning the whole shop.
ELASTICITY = {
    "Foodgrains, Oil & Masala": 0.3,
    "Bakery, Cakes & Dairy": 0.5,
    "Cleaning & Household": 0.5,
    "Beverages": 0.7,
    "Snacks & Branded Foods": 0.8,
    "Beauty & Hygiene": 1.1,
}
DEFAULT_ELASTICITY = 0.8

# Categories a household buys in bulk at month start.
STAPLES = {"Foodgrains, Oil & Masala", "Cleaning & Household"}

RAW_RULES = [
    ("Snacks & Branded Foods",   "Beverages",                 0.25),  # chips + cold drink
    ("Snacks & Branded Foods",   "Bakery, Cakes & Dairy",     0.20),  # biscuits + milk
    ("Bakery, Cakes & Dairy",    "Beverages",                 0.15),  # bread + tea
    ("Foodgrains, Oil & Masala", "Cleaning & Household",      0.10),  # monthly restock
    ("Snacks & Branded Foods",   "Snacks & Branded Foods",    0.15),  # party shopping
    ("Beauty & Hygiene",         "Beauty & Hygiene",          0.10),  # personal care
    ("Foodgrains, Oil & Masala", "Foodgrains, Oil & Masala",  0.05),  # oil + masala
]

STORES = {
    # A residential kirana: steady all day, busiest mid-morning and after
    # work, busier at the weekend, and strongly tied to the salary cycle.
    "S1": {
        "tx_per_day": 45,
        # Items per bill. A kirana visit is often a household top-up of
        # several things -- the main reason its bills are larger.
        "basket_sizes": {1: 0.30, 2: 0.25, 3: 0.19, 4: 0.12, 5: 0.08, 6: 0.06},
        "open_hours": list(range(8, 22)),
        "peak_hours": [9, 10, 11, 18, 19, 20],
        "day_factor": [1.00, 0.88, 0.98, 1.05, 1.15, 1.40, 1.30],  # Mon..Sun
        "salary_effect": True,
        # Share of single-item bills by category.
        "category_mix": {
            "Foodgrains, Oil & Masala": 0.28,
            "Bakery, Cakes & Dairy": 0.22,
            "Snacks & Branded Foods": 0.18,
            "Beverages": 0.14,
            "Cleaning & Household": 0.10,
            "Beauty & Hygiene": 0.08,
        },
        "rules": RAW_RULES,
    },
    # A kiosk by the station: commuter rushes either side of the working
    # day, near-empty at the weekend. People buy singles on the way past,
    # so the month cycle barely touches it.
    "S2": {
        "tx_per_day": 70,
        # Mostly a single item grabbed on the way past.
        "basket_sizes": {1: 0.62, 2: 0.30, 3: 0.08},
        # Every purchase here is a small impulse buy, so price bites harder
        # than at the kirana: elasticities are scaled up by this factor.
        "price_sensitivity": 1.6,
        "open_hours": list(range(6, 23)),
        "peak_hours": [7, 8, 9, 18, 19, 20, 21],
        "day_factor": [1.22, 1.20, 1.15, 1.20, 1.28, 0.58, 0.42],
        "salary_effect": False,
        # Grab-and-go: tea, snacks, water, biscuits. Staples and detergent
        # are near-absent -- nobody carries rice onto a train.
        "category_mix": {
            "Snacks & Branded Foods": 0.36,
            "Beverages": 0.34,
            "Bakery, Cakes & Dairy": 0.18,
            "Beauty & Hygiene": 0.08,
            "Cleaning & Household": 0.02,
            "Foodgrains, Oil & Masala": 0.02,
        },
        "rules": [
            ("Snacks & Branded Foods", "Beverages",              0.45),  # chips + drink
            ("Bakery, Cakes & Dairy",  "Beverages",              0.25),  # bun + tea
            ("Snacks & Branded Foods", "Bakery, Cakes & Dairy",  0.20),  # biscuits + milk
            ("Snacks & Branded Foods", "Snacks & Branded Foods", 0.10),
        ],
    },
}


def build_rules(store_catalog: pd.DataFrame, raw_rules=RAW_RULES):
    """Resolve a shop's pairing rules against its own catalogue."""
    def pool(name):
        return store_catalog[store_catalog["category"] == name]["sku"].tolist()

    rules = []
    for cat_a, cat_b, weight in raw_rules:
        a, b = pool(cat_a), pool(cat_b)
        if a and b:
            rules.append((a, b, weight))
    if not rules:
        raise SystemExit("No valid pairing rules for this store's catalogue")
    total = sum(w for _, _, w in rules)
    return [(a, b, w / total) for a, b, w in rules]


def price_weights(price_of: dict, category_of: dict, sensitivity: float = 1.0) -> dict:
    """Relative purchase frequency per SKU: cheaper sells more often, to a
    degree set by how much of a necessity the category is and how
    price-sensitive the shop's customers are."""
    return {
        sku: max(float(p), 1.0)
        ** -(ELASTICITY.get(category_of[sku], DEFAULT_ELASTICITY) * sensitivity)
        for sku, p in price_of.items()
    }


def choose(pool: list[str], weights: dict, rng=random) -> str:
    return rng.choices(pool, weights=[weights[s] for s in pool], k=1)[0]


def pick_pair(rules, weights: dict):
    r = random.random()                     # NOSONAR -- sample data generation only, not security-sensitive
    cumulative = 0.0
    chosen = rules[-1]
    for a_pool, b_pool, weight in rules:
        cumulative += weight
        if r <= cumulative:
            chosen = (a_pool, b_pool, weight)
            break
    a_pool, b_pool, _ = chosen
    sku_a = choose(a_pool, weights)
    sku_b = choose(b_pool, weights)
    attempts = 0
    while sku_b == sku_a and attempts < 10:
        sku_b = choose(b_pool, weights)
        attempts += 1
    return sku_a, sku_b


def pick_single(category_mix: dict, pools: dict, weights: dict) -> str:
    """One-item bill: choose the category by the shop's format, then a product."""
    cats = [c for c in category_mix if pools.get(c)]
    cat = random.choices(cats, weights=[category_mix[c] for c in cats], k=1)[0]     # NOSONAR -- sample data generation only, not security-sensitive
    return choose(pools[cat], weights)


def signature_pairs(code: str, rules, weights: dict) -> list[tuple[str, str]]:
    """The shop's handful of habitual pairings.

    Drawn from their own seed so they stay the same every time the data is
    regenerated -- a demo that suggests different bundles each day would be
    less believable than one that shows the same habits sharpening.
    """
    rng = random.Random(f"signature-{code}")
    pairs: list[tuple[str, str]] = []
    # The complementary rules come first in RAW_RULES; prefer them.
    candidates = rules[: max(3, len(rules) // 2)]
    attempts = 0
    while len(pairs) < SIGNATURE_PAIRS and attempts < 200:
        attempts += 1
        a_pool, b_pool, _ = rng.choice(candidates)  # NOSONAR -- seeded simulation
        # Habits form around everyday goods, not the priciest shelf item.
        a, b = choose(a_pool, weights, rng), choose(b_pool, weights, rng)
        pair = tuple(sorted((a, b)))
        if a != b and pair not in pairs:
            pairs.append(pair)
    return pairs


def pick_signature(pairs: list[tuple[str, str]]) -> tuple[str, str]:
    """Zipf-like: the first pairing is the strongest, each next one weaker."""
    weights = [1 / (i + 1) for i in range(len(pairs))]
    return random.choices(pairs, weights=weights, k=1)[0]       # NOSONAR -- sample data generation only, not security-sensitive


def pick_hour(profile) -> int:
    """Trade happens all day; peaks are weighted, not exclusive."""
    hours = profile["open_hours"]
    weights = [3.2 if h in profile["peak_hours"] else 1.0 for h in hours]
    return random.choices(hours, weights=weights, k=1)[0]  # NOSONAR -- seeded simulation


def month_factor(day_of_month: int, profile) -> float:
    """More bills in the first days after salaries, fewer as the month runs out."""
    if not profile["salary_effect"]:
        return 1.02 if day_of_month <= 5 else 1.0
    if day_of_month <= 5:
        return 1.20
    if day_of_month <= 7:
        return 1.08
    if day_of_month >= 26:
        return 0.92
    return 1.0


def quantity(category: str, day_of_month: int, profile) -> int:
    """Singles, except staples -- which are bought in twos at month start."""
    if category not in STAPLES:
        return 1
    if profile["salary_effect"] and day_of_month <= 7:
        r = random.random()  # NOSONAR -- seeded simulation
        return 3 if r < 0.10 else 2 if r < 0.55 else 1
    return 2 if random.random() < (0.15 if profile["salary_effect"] else 0.05) else 1  # NOSONAR -- seeded simulation


def generate_store(code: str, profile, now: datetime) -> pd.DataFrame:
    catalog = pd.read_excel(BASE / f"product_catalog_{code}.xlsx")
    skus = catalog["sku"].tolist()
    price_of = dict(zip(catalog["sku"], catalog["sell_price"]))
    category_of = dict(zip(catalog["sku"], catalog["category"]))
    weights = price_weights(price_of, category_of, profile.get("price_sensitivity", 1.0))
    sizes = list(profile["basket_sizes"])
    size_weights = list(profile["basket_sizes"].values())
    pools = catalog.groupby("category")["sku"].apply(list).to_dict()
    rules = build_rules(catalog, profile["rules"])
    signatures = signature_pairs(code, rules, weights)

    today = now.date()
    first = today - timedelta(weeks=WEEKS)
    elapsed = now.minute / 60  # share of the current hour already gone

    rows = []
    bill = 0
    day = first
    while day <= today:
        factor = (
            profile["day_factor"][day.weekday()]
            * month_factor(day.day, profile)
            * random.uniform(0.88, 1.12)
        )
        bills_today = max(1, round(profile["tx_per_day"] * factor))

        for _ in range(bills_today):
            hour = pick_hour(profile)
            # Today stops at the present moment: nothing from later hours,
            # and only the elapsed share of the hour we are in.
            if day == today and (
                hour > now.hour or (hour == now.hour and random.random() > elapsed)  # NOSONAR -- seeded simulation
            ):
                continue

            size = random.choices(sizes, weights=size_weights, k=1)[0]  # NOSONAR -- seeded simulation
            if size == 1:
                basket = [pick_single(profile["category_mix"], pools, weights)]
            else:
                # A multi-item bill is built around one plausible pairing,
                # then topped up with other things the household needed.
                if signatures and random.random() < SIGNATURE_SHARE:  # NOSONAR -- seeded simulation
                    basket = list(pick_signature(signatures))
                else:
                    basket = list(pick_pair(rules, weights))
                tries = 0
                while len(basket) < size and tries < 20:
                    tries += 1
                    extra = pick_single(profile["category_mix"], pools, weights)
                    if extra not in basket:
                        basket.append(extra)

            bill += 1
            for sku in basket:
                rows.append({
                    "date": day.isoformat(),
                    "hour": hour,
                    "transaction_id": f"{code}-{bill:06d}",
                    "sku": sku,
                    "qty": quantity(category_of[sku], day.day, profile),
                    "unit_price": price_of[sku],
                })
        day += timedelta(days=1)

    df = pd.DataFrame(rows)
    unknown = set(df["sku"]) - set(skus)
    assert not unknown, f"{code} sold SKUs it does not stock: {unknown}"
    return df


def main(now: datetime | None = None) -> datetime:
    now = now or datetime.now(IST)
    random.seed(42)
    print(f"Sale lines: {WEEKS} weeks to {now:%a %d %b %Y, %H:%M} IST")
    for code, profile in STORES.items():
        df = generate_store(code, profile, now)
        out = BASE / f"sales_lines_{code}.xlsx"
        df.to_excel(out, index=False)
        bills = df["transaction_id"].nunique()
        days = df["date"].nunique()
        print(
            f"  {code}: {len(df):,} lines, {bills:,} bills over {days} days "
            f"({df['date'].min()} to {df['date'].max()})"
        )
    return now


if __name__ == "__main__":
    main()
