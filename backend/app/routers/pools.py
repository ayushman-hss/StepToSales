"""Group-buying pool endpoints.

Reads and writes go through ``services.pooling.repository``; all pricing and
settlement maths lives in the pure domain layer, which this router only calls.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..db import get_session
from ..dependencies import get_current_store, own_store_code
from ..models import Product, Store
from ..models_pooling import BuyingPool, PoolEvent, PoolOrder, PoolProduct
from ..schemas_pooling import (
    PlaceOrderIn,
    PoolEventOut,
    PoolOut,
    PoolProductOut,
    PoolStoreOut,
    PoolSummaryOut,
    StoreLineOut,
    TierOut,
    WithdrawIn,
)
from ..services.pooling import PoolError, Strategy
from ..services.pooling.repository import (
    RepositoryError,
    load_pool,
    persist_settlement,
    record_event,
    store_ids_by_code,
)

# Every member shop can see the whole pool -- that is the point of it -- but
# each one can only order or withdraw for itself.
router = APIRouter(
    prefix="/api/pools",
    tags=["pools"],
    dependencies=[Depends(get_current_store)],
)


def _strategy(value: str) -> Strategy:
    try:
        return Strategy(value)
    except ValueError:
        raise HTTPException(
            400,
            f"unknown strategy {value!r}; expected one of "
            f"{[s.value for s in Strategy]}",
        )


def _names_for(session: Session, skus: set[str]) -> dict[str, str]:
    if not skus:
        return {}
    rows = session.exec(select(Product).where(Product.sku.in_(skus))).all()
    return {p.sku: p.name for p in rows}


def _load(session: Session, code: str):
    try:
        return load_pool(session, code)
    except RepositoryError as exc:
        raise HTTPException(404, str(exc))


def _render(session: Session, code: str, strategy: Strategy) -> PoolOut:
    domain, row = _load(session, code)
    try:
        settlement = domain.project(strategy)
    except PoolError as exc:
        raise HTTPException(409, str(exc))

    names = _names_for(session, {p.sku for p in settlement.products})
    products = []
    for p in settlement.products:
        table = domain.price_lists[p.sku]
        products.append(
            PoolProductOut(
                sku=p.sku,
                name=names.get(p.sku, p.sku),
                supplier_id=p.supplier_id,
                price_list_version=p.price_list_version,
                total_qty=p.total_qty,
                pooled_unit_price=p.pooled_unit_price,
                tier_label=p.tier_label,
                units_to_next_tier=p.units_to_next_tier,
                next_tier_unit_price=p.next_tier_unit_price,
                invoice_total=p.invoice_total,
                total_savings=p.total_savings,
                tiers=[
                    TierOut(
                        min_qty=t.min_qty,
                        max_qty=t.max_qty,
                        unit_price=t.unit_price,
                        label=t.label,
                    )
                    for t in table.tiers
                ],
                lines=[
                    StoreLineOut(
                        store=s,
                        qty=p.qty_by_store[s],
                        cost_alone=p.cost_alone_by_store[s],
                        payable=p.payable_by_store[s],
                        savings=p.savings_by_store[s],
                    )
                    for s in sorted(p.qty_by_store)
                ],
            )
        )

    return PoolOut(
        code=row.code,
        name=row.name,
        status=row.status,
        strategy=strategy.value,
        rotation=row.rotation,
        closes_at=row.closes_at,
        invoice_total=settlement.invoice_total,
        total_savings=settlement.total_savings,
        products=products,
        stores=[
            PoolStoreOut(
                store=s.store,
                cost_alone=s.cost_alone,
                payable=s.payable,
                savings=s.savings,
                savings_pct=round(s.savings_pct, 2),
            )
            for s in settlement.stores
        ],
    )


@router.get("", response_model=list[PoolSummaryOut])
def list_pools(session: Session = Depends(get_session)):
    out = []
    for row in session.exec(select(BuyingPool).order_by(BuyingPool.code)).all():
        domain, _ = load_pool(session, row.code)
        try:
            total = domain.project(Strategy(row.strategy)).total_savings
        except PoolError:
            total = 0
        out.append(
            PoolSummaryOut(
                code=row.code,
                name=row.name,
                status=row.status,
                store_count=len(domain.stores),
                total_savings=total,
            )
        )
    return out


@router.get("/{code}", response_model=PoolOut)
def get_pool(
    code: str,
    strategy: str = Query("pro_rata"),
    session: Session = Depends(get_session),
):
    return _render(session, code, _strategy(strategy))


@router.post("/{code}/orders", response_model=PoolOut)
def place_order(
    code: str,
    body: PlaceOrderIn,
    strategy: str = Query("pro_rata"),
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    store_code = own_store_code(body.store_id, store)
    domain, row = _load(session, code)

    # Validate against the domain first so a rejected order never reaches the
    # database and the error text matches the rules the settlement enforces.
    try:
        domain.place_order(store_code, body.sku, body.qty)
    except PoolError as exc:
        raise HTTPException(409, str(exc))

    existing = session.exec(
        select(PoolOrder)
        .where(PoolOrder.pool_id == row.id)
        .where(PoolOrder.store_id == store.id)
        .where(PoolOrder.sku == body.sku)
    ).first()
    if existing:
        existing.qty = body.qty
        session.add(existing)
    else:
        session.add(
            PoolOrder(
                pool_id=row.id, store_id=store.id, sku=body.sku, qty=body.qty
            )
        )
    record_event(
        session, row.id, actor=store_code, kind="ordered",
        sku=body.sku, qty=body.qty,
    )
    session.commit()
    return _render(session, code, _strategy(strategy))


@router.post("/{code}/withdraw", response_model=PoolOut)
def withdraw(
    code: str,
    body: WithdrawIn,
    strategy: str = Query("pro_rata"),
    session: Session = Depends(get_session),
    store: Store = Depends(get_current_store),
):
    store_code = own_store_code(body.store_id, store)
    domain, row = _load(session, code)
    try:
        domain.withdraw(store_code, body.sku)
    except PoolError as exc:
        raise HTTPException(409, str(exc))

    stmt = (
        select(PoolOrder)
        .where(PoolOrder.pool_id == row.id)
        .where(PoolOrder.store_id == store.id)
    )
    if body.sku:
        stmt = stmt.where(PoolOrder.sku == body.sku)
    for order in session.exec(stmt).all():
        session.delete(order)
    record_event(
        session, row.id, actor=store_code, kind="withdrew", sku=body.sku,
    )
    session.commit()
    return _render(session, code, _strategy(strategy))


@router.post("/{code}/close", response_model=PoolOut)
def close_pool(
    code: str,
    strategy: str = Query("pro_rata"),
    session: Session = Depends(get_session),
):
    chosen = _strategy(strategy)
    domain, row = _load(session, code)
    try:
        settlement = domain.close(chosen)
    except PoolError as exc:
        raise HTTPException(409, str(exc))

    record_event(session, row.id, actor="system", kind="locked")
    persist_settlement(session, row, settlement, chosen)
    session.commit()
    return _render(session, code, chosen)


@router.post("/{code}/reopen", response_model=PoolOut)
def reopen_pool(
    code: str,
    strategy: str = Query("pro_rata"),
    session: Session = Depends(get_session),
):
    """Demo convenience: put a settled pool back to open and clear its lines."""
    from ..models_pooling import PoolSettlementLine

    domain, row = _load(session, code)
    for line in session.exec(
        select(PoolSettlementLine).where(PoolSettlementLine.pool_id == row.id)
    ).all():
        session.delete(line)
    row.status = "open"
    row.settled_at = None
    row.rotation = row.rotation + 1
    session.add(row)
    record_event(session, row.id, actor="system", kind="reopened")
    session.commit()
    return _render(session, code, _strategy(strategy))


@router.get("/{code}/events", response_model=list[PoolEventOut])
def pool_events(code: str, session: Session = Depends(get_session)):
    _, row = _load(session, code)
    rows = session.exec(
        select(PoolEvent)
        .where(PoolEvent.pool_id == row.id)
        .order_by(PoolEvent.id.desc())
    ).all()
    return [
        PoolEventOut(
            actor=e.actor,
            kind=e.kind,
            detail=e.detail,
            created_at=e.created_at.isoformat(timespec="seconds"),
        )
        for e in rows
    ]
