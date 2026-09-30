from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from sqlmodel import Session, select
from sqlalchemy import delete as sa_delete
import pandas as pd

from ..db import get_session
from ..dependencies import get_current_store
from ..models import Store, Upload, SaleLine, Product, BundleSuggestion
from ..schemas import BundleSuggestionOut, BundleActionIn
from ..services.parser import parse_sales_lines
from ..services.bundles import generate_suggestions
from ..services.associations import (
    DEFAULT_MIN_LIFT,
    default_min_support,
    multi_item_baskets,
)

router = APIRouter(prefix="/api/bundles", tags=["bundles"])


@router.post("/upload-lines")
async def upload_sales_lines(
    mode: str = Query("replace", pattern="^(replace|append)$"),
    file: UploadFile = File(...),
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    """Upload sale line items for the authenticated store."""
    try:
        df = parse_sales_lines(file.file)
    except Exception as e:
        raise HTTPException(400, f"Parse error: {e}")

    # "replace" makes a re-upload authoritative: correcting the file and
    # uploading again replaces the store's lines instead of stacking another
    # copy on top of them. "append" is for genuinely new periods.
    removed = 0
    if mode == "replace":
        result = session.execute(
            sa_delete(SaleLine).where(SaleLine.store_id == current.id)
        )
        removed = result.rowcount or 0

    upload = Upload(filename=file.filename, rows=len(df))
    session.add(upload)
    session.flush()

    session.add_all([
        SaleLine(
            store_id=current.id, upload_id=upload.id,
            date=r["date"], hour=int(r["hour"]),
            transaction_id=r["transaction_id"], sku=r["sku"],
            qty=int(r["qty"]), unit_price=float(r["unit_price"]),
        )
        for r in df.to_dict(orient="records")
    ])
    session.commit()
    return {
        "rows": len(df),
        "upload_id": upload.id,
        "mode": mode,
        "replaced_rows": removed,
    }


@router.post("/generate")
def generate(
    margin_floor_pct: float = Query(0.15, ge=0.0, lt=1.0),
    min_support_tx: int | None = Query(None, ge=1),
    min_lift: float = Query(DEFAULT_MIN_LIFT, gt=0.0),
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    """Recompute bundle suggestions for the authenticated store."""
    rows = session.exec(
        select(SaleLine.upload_id, SaleLine.transaction_id, SaleLine.sku)
        .where(SaleLine.store_id == current.id)
    ).all()
    if not rows:
        raise HTTPException(400, "No line-item data. Upload sales lines first.")

    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df["basket_id"] = (
        df["upload_id"].astype(str) + ":" + df["transaction_id"].astype(str)
    )

    # Snapshot decisions as plain values before deleting, so a regenerate
    # refreshes every pair's numbers without discarding what the user already
    # approved or rejected -- and without leaving stale rows behind.
    previous = {
        (s.sku_a, s.sku_b): (s.status, s.approved_price)
        for s in session.exec(
            select(BundleSuggestion).where(BundleSuggestion.store_id == current.id)
        ).all()
    }
    session.execute(
        sa_delete(BundleSuggestion).where(BundleSuggestion.store_id == current.id)
    )
    session.commit()

    effective_support = (
        min_support_tx
        if min_support_tx is not None
        else default_min_support(multi_item_baskets(df))
    )
    stats: dict = {}
    suggestions = generate_suggestions(
        session, current.id, df, margin_floor_pct,
        min_support_tx=effective_support, min_lift=min_lift, stats=stats,
    )

    # SKUs sold but absent from the catalogue can never become a bundle --
    # say so instead of quietly returning a shorter list.
    catalog_skus = set(
        session.exec(
            select(Product.sku).where(Product.store_id == current.id)
        ).all()
    )
    unmatched = sorted(set(df["sku"].astype(str)) - catalog_skus)

    kept = 0
    for s in suggestions:
        prev = previous.get((s.sku_a, s.sku_b))
        if prev and prev[0] in ("approved", "rejected"):
            s.status, s.approved_price = prev
            kept += 1
    session.commit()

    return {
        "suggestions": len(suggestions),
        "decisions_kept": kept,
        "baskets": int(df["basket_id"].nunique()),
        "min_support_tx": effective_support,
        "min_lift": min_lift,
        "unmatched_sku_count": len(unmatched),
        "unmatched_skus": unmatched[:10],
        **stats,
    }


@router.get("", response_model=list[BundleSuggestionOut])
def list_bundles(
    status: str = Query("all"),
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    """Bundle suggestions for the authenticated store."""
    stmt = select(BundleSuggestion).where(
        BundleSuggestion.store_id == current.id
    )
    if status != "all":
        stmt = stmt.where(BundleSuggestion.status == status)
    suggestions = session.exec(stmt.order_by(BundleSuggestion.lift.desc())).all()

    skus = {s.sku_a for s in suggestions} | {s.sku_b for s in suggestions}
    products = {
        p.sku: p for p in session.exec(
            select(Product)
            .where(Product.store_id == current.id)
            .where(Product.sku.in_(skus))
        ).all()
    } if skus else {}

    out = []
    for s in suggestions:
        a = products.get(s.sku_a)
        b = products.get(s.sku_b)
        out.append(BundleSuggestionOut(
            id=s.id, sku_a=s.sku_a, sku_b=s.sku_b,
            name_a=a.name if a else s.sku_a,
            name_b=b.name if b else s.sku_b,
            transactions_with_both=s.transactions_with_both,
            total_transactions=s.total_transactions,
            confidence=s.confidence, lift=s.lift,
            separate_price=s.separate_price,
            separate_margin_pct=(s.separate_price - s.separate_cost) / s.separate_price
                if s.separate_price else 0,
            suggested_price=s.suggested_price,
            suggested_margin_pct=s.suggested_margin_pct,
            margin_floor_pct=s.margin_floor_pct,
            status=s.status,
            approved_price=s.approved_price,
        ))
    return out


def _owned_suggestion(
    suggestion_id: int, current: Store, session: Session
) -> BundleSuggestion:
    """Load a suggestion and confirm it belongs to the authenticated store.

    Without this check, S1 could approve or reject S2's bundles by guessing
    an integer id. The 404 (not 403) is deliberate: don't confirm the row
    exists to someone who has no business seeing it.
    """
    s = session.get(BundleSuggestion, suggestion_id)
    if not s or s.store_id != current.id:
        raise HTTPException(404, "Suggestion not found")
    return s


@router.post("/{suggestion_id}/approve")
def approve(
    suggestion_id: int,
    action: BundleActionIn,
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    s = _owned_suggestion(suggestion_id, current, session)
    s.status = "approved"
    s.approved_price = action.price if action.price is not None else s.suggested_price
    session.commit()
    return {"ok": True, "approved_price": s.approved_price}


@router.post("/{suggestion_id}/reject")
def reject(
    suggestion_id: int,
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    s = _owned_suggestion(suggestion_id, current, session)
    s.status = "rejected"
    session.commit()
    return {"ok": True}