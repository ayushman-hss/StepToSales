from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlmodel import Session, select

from ..db import get_session
from ..dependencies import get_current_store
from ..models import Product, Store
from ..schemas import ProductOut
from ..services.parser import parse_product_catalog

router = APIRouter(prefix="/api/products", tags=["products"])


def _to_out(p: Product) -> ProductOut:
    margin = (p.sell_price - p.cost_price) / p.sell_price if p.sell_price else 0
    return ProductOut(
        id=p.id, sku=p.sku, name=p.name,
        cost_price=p.cost_price, sell_price=p.sell_price,
        margin_pct=margin,
    )


@router.post("/upload")
async def upload_catalog(
    file: UploadFile = File(...),
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    """Upload a price list. The store comes from the session, not the query string."""
    try:
        df = parse_product_catalog(file.file)
    except Exception as e:
        raise HTTPException(400, f"Parse error: {e}")

    existing = {
        p.sku: p
        for p in session.exec(
            select(Product).where(Product.store_id == current.id)
        ).all()
    }

    new_count, updated = 0, 0
    for r in df.to_dict(orient="records"):
        if r["sku"] in existing:
            p = existing[r["sku"]]
            p.name = r["name"]
            p.cost_price = r["cost_price"]
            p.sell_price = r["sell_price"]
            updated += 1
        else:
            session.add(Product(
                store_id=current.id, sku=r["sku"], name=r["name"],
                cost_price=r["cost_price"], sell_price=r["sell_price"],
            ))
            new_count += 1

    session.commit()
    return {"new": new_count, "updated": updated}


@router.get("", response_model=list[ProductOut])
def list_products(
    current: Store = Depends(get_current_store),
    session: Session = Depends(get_session),
):
    """Every product in the authenticated store's catalogue."""
    items = session.exec(
        select(Product).where(Product.store_id == current.id)
    ).all()
    return [_to_out(p) for p in items]