"""Rebuild the demo database into a known-good, self-consistent state.

Loads hourly footfall, per-store catalogues and per-store sale lines, then
regenerates bundle suggestions. Safe to re-run: every load replaces the
previous contents for that store rather than stacking another copy on top.

    cd backend && python scripts/reset_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from decimal import Decimal

from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.db import engine, init_db
from app.models import Store, Upload, HourlyData, SaleLine, Product, BundleSuggestion
from app.models_pooling import (
    BuyingPool,
    PoolEvent,
    PoolOrder,
    PoolProduct,
    PoolSettlementLine,
    PriceList,
    PriceTier,
    Supplier,
)
from app.services.pooling.repository import record_event
from app.services.parser import parse_excel, parse_product_catalog, parse_sales_lines
from app.services.associations import (
    DEFAULT_MIN_LIFT,
    default_min_support,
    multi_item_baskets,
)
from app.services.pooling import to_paise
from app.services.bundles import generate_suggestions

from app.models import (
    Store, Upload, HourlyData, SaleLine, Product, BundleSuggestion, StoreUser,
    AuthSession, LiveEvent, AlertSent, AlertLinkCode,
)
from app.services.live.engine import LIVE_UPLOAD
from app.services.auth import hash_password, normalise_username

import generate_bundle_sample
import generate_sample

#: Demo logins. Passwords are deliberately not the store code itself --
#: S1/s1shop reads like a real credential, S1/S1 does not.
DEMO_CREDENTIALS = {
    "S1": "s1shop",
    "S2": "s2shop",
    "S3": "s3shop",
}
#: Shown next to the code once a shop logs in. Matches the profiles in
#: generate_bundle_sample.py.
STORE_NAMES = {"S1": "Residential kirana", "S2": "Station kiosk"}

BASE = Path(__file__).resolve().parents[1]
STORES = ["S1", "S2"]
MARGIN_FLOOR = 0.10  # matches the UI default; see BundlePage.tsx

# Two suppliers with different volume-break shapes, so the demo shows that
# tier boundaries are a property of the supplier, not of the app.
SUPPLIERS = [
    {
        "code": "SUP1",
        "name": "Koramangala Wholesale Traders",
        "breaks": [(1, 19), (20, 49), (50, None)],
        "discounts": [1.00, 0.92, 0.85],
        "take": 6,
    },
    {
        "code": "SUP2",
        "name": "Hosur Road Cash & Carry",
        "breaks": [(1, 24), (25, 99), (100, None)],
        "discounts": [1.00, 0.94, 0.88],
        "take": 6,
    },
]

POOL_CODE = "koramangala"
POOL_NAME = "Koramangala Neighborhood Pool"
#: Seed orders that already reach a middle tier, so the live view has
#: something to show and the "add N more" hint is visible straight away.
SEED_ORDERS = [("S1", 0, 15), ("S2", 0, 20), ("S1", 1, 8), ("S2", 6, 30)]
#: A third member that buys through the pool but runs no POS integration --
#: it has no footfall or sales data, which is exactly how a real buying group
#: picks up neighbours who are not customers of the analytics product.
POOL_ONLY_STORES = [("S3", "Ejipura Provision Store")]


def get_store(session: Session, code: str) -> Store:
    store = session.exec(select(Store).where(Store.code == code)).first()
    if not store:
        store = Store(code=code, name=code)
        session.add(store)
        session.commit()
        session.refresh(store)
    return store


def load_hourly(session: Session) -> None:
    df = parse_excel(BASE / "sample-data.xlsx")
    session.execute(sa_delete(HourlyData))
    upload = Upload(filename="sample-data.xlsx", rows=len(df))
    session.add(upload)
    session.flush()
    for r in df.to_dict("records"):
        store = get_store(session, r["store_id"])
        session.add(HourlyData(
            store_id=store.id, upload_id=upload.id,
            date=r["date"], hour=int(r["hour"]),
            footfall=int(r["footfall"]), transactions=int(r["transactions"]),
            sales=float(r["sales"]),
        ))
    session.commit()
    print(f"  hourly_data      : {len(df)} rows")


def load_store(session: Session, code: str) -> None:
    store = get_store(session, code)

    cat = parse_product_catalog(BASE / f"product_catalog_{code}.xlsx")
    session.execute(sa_delete(Product).where(Product.store_id == store.id))
    for r in cat.to_dict("records"):
        session.add(Product(
            store_id=store.id, sku=r["sku"], name=r["name"],
            cost_price=r["cost_price"], sell_price=r["sell_price"],
        ))

    lines = parse_sales_lines(BASE / f"sales_lines_{code}.xlsx")
    session.execute(sa_delete(SaleLine).where(SaleLine.store_id == store.id))
    upload = Upload(filename=f"sales_lines_{code}.xlsx", rows=len(lines))
    session.add(upload)
    session.flush()
    for r in lines.to_dict("records"):
        session.add(SaleLine(
            store_id=store.id, upload_id=upload.id,
            date=r["date"], hour=int(r["hour"]),
            transaction_id=r["transaction_id"], sku=r["sku"],
            qty=int(r["qty"]), unit_price=float(r["unit_price"]),
        ))
    session.commit()

    lines["basket_id"] = str(upload.id) + ":" + lines["transaction_id"].astype(str)
    session.execute(
        sa_delete(BundleSuggestion).where(BundleSuggestion.store_id == store.id)
    )
    session.commit()

    support = default_min_support(multi_item_baskets(lines))
    stats: dict = {}
    sugg = generate_suggestions(
        session, store.id, lines, MARGIN_FLOOR,
        min_support_tx=support, min_lift=DEFAULT_MIN_LIFT, stats=stats,
    )

    catalog_skus = set(cat["sku"].astype(str))
    unmatched = sorted(set(lines["sku"].astype(str)) - catalog_skus)
    print(
        f"  {code}: products={len(cat)} lines={len(lines)} "
        f"baskets={lines['basket_id'].nunique()} min_support={support} "
        f"-> {len(sugg)} suggestions"
    )
    print(
        f"      candidate_pairs={stats.get('candidate_pairs')} "
        f"dropped_missing_product={stats.get('dropped_missing_product')} "
        f"dropped_no_discount={stats.get('dropped_no_discount')}"
    )
    if unmatched:
        print(f"      WARNING {len(unmatched)} SKUs sold but not in catalogue: "
              f"{unmatched[:6]}{'...' if len(unmatched) > 6 else ''}")


def _tier_prices(cost_paise: int, discounts: list[float]) -> list[int]:
    """Whole-rupee wholesale prices, guaranteed never to rise with volume."""
    prices = []
    previous = None
    for d in discounts:
        p = max(100, round(cost_paise * d / 100) * 100)
        if previous is not None:
            p = min(p, previous)
        prices.append(p)
        previous = p
    return prices


def load_pools(session: Session) -> None:
    # Wipe children first: these tables are only ever rebuilt wholesale here.
    for model in (
        PoolSettlementLine, PoolEvent, PoolOrder, PoolProduct,
        BuyingPool, PriceTier, PriceList, Supplier,
    ):
        session.execute(sa_delete(model))
    session.commit()

    catalog = parse_product_catalog(BASE / "product_catalog_S1.xlsx")
    catalog = catalog.sort_values("sku").reset_index(drop=True)

    pool = BuyingPool(code=POOL_CODE, name=POOL_NAME, status="open",
                      strategy="pro_rata")
    session.add(pool)
    session.flush()

    offset = 0
    pooled_skus: list[str] = []
    for spec in SUPPLIERS:
        supplier = Supplier(code=spec["code"], name=spec["name"])
        session.add(supplier)
        session.flush()

        rows = catalog.iloc[offset:offset + spec["take"]]
        offset += spec["take"]
        for r in rows.to_dict("records"):
            cost_paise = to_paise(Decimal(str(round(r["cost_price"], 2))))
            price_list = PriceList(
                supplier_id=supplier.id, sku=r["sku"], version="2026-09-01",
                valid_from="2026-09-01",
            )
            session.add(price_list)
            session.flush()
            prices = _tier_prices(cost_paise, spec["discounts"])
            for (lo, hi), price in zip(spec["breaks"], prices):
                session.add(PriceTier(
                    price_list_id=price_list.id, min_qty=lo, max_qty=hi,
                    unit_price=price,
                ))
            session.add(PoolProduct(
                pool_id=pool.id, sku=r["sku"], price_list_id=price_list.id,
            ))
            pooled_skus.append(r["sku"])

    session.commit()
    record_event(session, pool.id, actor="system", kind="opened",
                 products=len(pooled_skus))

    for code, name in POOL_ONLY_STORES:
        if not session.exec(select(Store).where(Store.code == code)).first():
            session.add(Store(code=code, name=name))
    session.commit()

    stores = {s.code: s for s in session.exec(select(Store)).all()}
    placed = 0
    for store_code, index, qty in SEED_ORDERS:
        store = stores.get(store_code)
        if store is None or index >= len(pooled_skus):
            continue
        sku = pooled_skus[index]
        session.add(PoolOrder(
            pool_id=pool.id, store_id=store.id, sku=sku, qty=qty,
        ))
        record_event(session, pool.id, actor=store_code, kind="ordered",
                     sku=sku, qty=qty)
        placed += 1
    session.commit()

    print(f"  pools: 1 open ({POOL_NAME})")
    print(f"      {len(SUPPLIERS)} suppliers, {len(pooled_skus)} products "
          f"with tiered pricing, {placed} seed orders")

def load_users(session: Session) -> None:
    """Wipe and recreate demo logins.

    Sessions are transient and are created on login, so only StoreUser rows
    need seeding. Every store listed in DEMO_CREDENTIALS gets one; a store
    that appears in POOL_ONLY_STORES (S3) still gets a login so you can sign
    in as it to see the pool from its side.
    """
    # Sessions point at users, so they go first. Everyone is logged out.
    session.execute(sa_delete(AuthSession))
    session.execute(sa_delete(StoreUser))
    session.commit()

    created = []
    for code, password in DEMO_CREDENTIALS.items():
        store = get_store(session, code)
        if code in STORE_NAMES and store.name in ("", code):
            store.name = STORE_NAMES[code]
            session.add(store)
        # Stored lower-case; logging in as "S1" or "s1" both work.
        session.add(StoreUser(
            store_id=store.id,
            username=normalise_username(code),
            password_hash=hash_password(password),
        ))
        created.append(f"{code}/{password}")
    session.commit()
    print(f"  users            : {len(created)} ({', '.join(created)})")

def main() -> None:
    print("Regenerating demo data up to the current hour...")
    now = generate_bundle_sample.main()
    generate_sample.main(now)
    init_db()
    with Session(engine) as session:
        print("Resetting demo data...")
        # Live events are rebuilt on top of fresh history, never kept across a
        # reset: they would sit in hours the new history already covers.
        session.execute(sa_delete(LiveEvent))
        # So the fresh day raises its alerts again. Linked Telegram chats are
        # kept: a phone connected once stays connected across resets.
        session.execute(sa_delete(AlertSent))
        session.execute(sa_delete(AlertLinkCode))
        session.commit()
        load_hourly(session)
        for code in STORES:
            load_store(session, code)
        load_pools(session)
        load_users(session)
        live = session.exec(select(Upload).where(Upload.filename == LIVE_UPLOAD)).first()
        if live is not None:
            session.execute(sa_delete(SaleLine).where(SaleLine.upload_id == live.id))
            session.execute(sa_delete(HourlyData).where(HourlyData.upload_id == live.id))
            session.delete(live)
            session.commit()
        print("Done.")


if __name__ == "__main__":
    main()
