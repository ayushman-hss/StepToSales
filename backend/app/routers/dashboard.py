from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Depends
from sqlmodel import Session, select
from typing import Optional
import pandas as pd

from ..db import get_session
from ..dependencies import get_current_store
from ..models import Store, Upload, HourlyData, StoreUser
from datetime import date, timedelta
from sqlalchemy import func

from ..schemas import Comparison, DashboardResponse, Period, UploadResponse, StoreOut
from ..services.parser import parse_excel
from ..services.insights import generate_insights, whatsapp_summary
from ..services.metrics import (
    compute_kpis,
    daily_series,
    heatmap_series,
    hourly_series,
    is_partial,
)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _short(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _period(df: pd.DataFrame, partial_date: Optional[str]) -> Period:
    """Describe the range actually present in the data, not the one requested.

    "All" has no dates in the request; the label must still say what it covers.
    """
    start = date.fromisoformat(df["date"].min())
    end = date.fromisoformat(df["date"].max())
    partial = partial_date is not None
    if start == end:
        label = _short(end) + (" so far" if partial else "")
    elif start.month == end.month:
        label = f"{start.day} to {end.day} {end:%b}"
    else:
        label = f"{start.day} {start:%b} to {end.day} {end:%b}"
    return Period(
        start=start.isoformat(),
        end=end.isoformat(),
        days=int(df["date"].nunique()),
        partial=partial,
        label=label,
    )


router = APIRouter(prefix="/api", tags=["dashboard"])


@router.post("/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: StoreUser = Depends(get_current_store),
):
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx or .xls files are accepted")

    try:
        df = parse_excel(file.file)
    except Exception as e:
        raise HTTPException(400, f"Parse error: {e}")

    if df.empty:
        raise HTTPException(400, "No valid rows found")

    if not user.store_id:
        raise HTTPException(403, "User is not linked to a store")

    # A store user can only upload for their own store.
    df = df[df["store_id"] == user.store.code]
    if df.empty:
        raise HTTPException(400, "File contains no rows for your store")

    # 1. Store already exists (it's this user's store), no upsert needed.
    store = user.store

    # 2. Register upload
    upload = Upload(filename=file.filename, rows=len(df))
    session.add(upload)
    session.flush()

    # 3. Bulk insert rows
    records = df.to_dict(orient="records")
    session.add_all([
        HourlyData(
            store_id=store.id,
            upload_id=upload.id,
            date=r["date"],
            hour=int(r["hour"]),
            footfall=int(r["footfall"]),
            transactions=int(r["transactions"]),
            sales=float(r["sales"]),
        )
        for r in records
    ])
    session.commit()

    return UploadResponse(
        upload_id=upload.id,
        rows=len(records),
        stores=[store.code],
        date_range=[df["date"].min(), df["date"].max()],
    )


def _load_df(
    session: Session,
    store_code: Optional[str],
    start: Optional[str],
    end: Optional[str],
) -> pd.DataFrame:
    stmt = (
        select(
            HourlyData.date,
            HourlyData.hour,
            HourlyData.footfall,
            HourlyData.transactions,
            HourlyData.sales,
            Store.code.label("store_id"),
        )
        .join(Store, Store.id == HourlyData.store_id)
    )

    if store_code and store_code != "all":
        stmt = stmt.where(Store.code == store_code)
    if start:
        stmt = stmt.where(HourlyData.date >= start)
    if end:
        stmt = stmt.where(HourlyData.date <= end)

    rows = session.exec(stmt).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r._mapping) for r in rows])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    user: StoreUser = Depends(get_current_store),
):
    store_code = user.store.code
    df = _load_df(session, store_code, start_date, end_date)
    if df.empty:
        raise HTTPException(404, "No data for the given filters")

    partial_date = _partial_date(session, store_code, df)
    period = _period(df, partial_date)
    title = f"Summary for {period.label}"

    return DashboardResponse(
        kpis=compute_kpis(df),
        hourly=hourly_series(df),
        daily=daily_series(df),
        heatmap=heatmap_series(df),
        insights=generate_insights(df, partial_date),
        whatsapp=whatsapp_summary(df, title, partial_date),
        period=period,
        data_through=_data_through(session, store_code),
        compare=_compare(session, store_code, df, period),
    )


def _partial_date(
    session: Session, store_code: Optional[str], df: pd.DataFrame
) -> Optional[str]:
    """The range's final date, if that day is still in progress.

    Judged against the week before it, so it works even when the range is a
    single day -- which on its own has no "usual closing time" to compare to.
    """
    end = df["date"].max()
    week_before = (date.fromisoformat(end) - timedelta(days=7)).isoformat()
    context = _load_df(session, store_code, week_before, end)
    if context.empty or context["date"].max() != end:
        return None
    return end if is_partial(context) else None


def _data_through(session: Session, store_code: Optional[str]) -> Optional[str]:
    """Latest date and hour held for this shop filter, regardless of range."""
    stmt = select(func.max(HourlyData.date)).join(Store, Store.id == HourlyData.store_id)
    if store_code and store_code != "all":
        stmt = stmt.where(Store.code == store_code)
    latest = session.exec(stmt).first()
    if not latest:
        return None
    hstmt = (
        select(func.max(HourlyData.hour))
        .join(Store, Store.id == HourlyData.store_id)
        .where(HourlyData.date == latest)
    )
    if store_code and store_code != "all":
        hstmt = hstmt.where(Store.code == store_code)
    hour = session.exec(hstmt).first()
    return f"{latest}T{int(hour):02d}"


def _compare(
    session: Session,
    store_code: Optional[str],
    df: pd.DataFrame,
    period: Period,
) -> Optional[Comparison]:
    """For a single day: the same weekday a week earlier, up to the same hour.

    Comparing a half-finished today with all of last Monday would always look
    like a bad day, so the earlier day is cut at the hour today has reached.
    """
    if period.start != period.end:
        return None
    day = date.fromisoformat(period.end)
    through = int(df["hour"].max())
    prior = day - timedelta(days=7)
    prev = _load_df(session, store_code, prior.isoformat(), prior.isoformat())
    if prev.empty:
        return None
    prev = prev[prev["hour"] <= through]
    when = f"by {through}:00" if period.partial else "all day"
    return Comparison(
        date=prior.isoformat(),
        label=f"last {DAY_NAMES[prior.weekday()]} {when}",
        through_hour=through,
        footfall=int(prev["footfall"].sum()),
        transactions=int(prev["transactions"].sum()),
        sales=float(prev["sales"].sum()),
    )


@router.get("/stores", response_model=list[StoreOut])
def list_stores(
    session: Session = Depends(get_session),
    user: StoreUser = Depends(get_current_store),
):
    return [StoreOut(code=user.store.code, name=user.store.name)]


@router.get("/health")
def health(session: Session = Depends(get_session)):
    has_data = session.exec(select(HourlyData).limit(1)).first() is not None
    return {"ok": True, "has_data": has_data}