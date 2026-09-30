from sqlmodel import SQLModel, Field
from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """Naive UTC, to match the TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Store(SQLModel, table=True):
    __tablename__ = "store"
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)   # "S1", "S2"
    name: str = ""

class StoreUser(SQLModel, table=True):
    """A login. Each one belongs to exactly one shop and sees only that shop."""
    __tablename__ = "store_user"
    id: Optional[int] = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    username: str = Field(index=True, unique=True)   # stored lower-cased
    password_hash: str
    created_at: datetime = Field(default_factory=utc_now)


class AuthSession(SQLModel, table=True):
    """A signed-in browser.

    Only a SHA-256 of the bearer token is kept, so a copy of this table is not
    a set of working logins. Named AuthSession so it never gets confused with
    sqlmodel's database Session.
    """
    __tablename__ = "auth_session"
    token_hash: str = Field(primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    user_id: int = Field(foreign_key="store_user.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(index=True)

class Upload(SQLModel, table=True):
    __tablename__ = "upload"
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    rows: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

class HourlyData(SQLModel, table=True):
    __tablename__ = "hourly_data"
    id: Optional[int] = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    upload_id: int = Field(foreign_key="upload.id", index=True)
    date: str = Field(index=True)     # YYYY-MM-DD
    hour: int = Field(index=True)     # 0-23
    footfall: int
    transactions: int
    sales: float

class Product(SQLModel, table=True):
    __tablename__ = "product"
    id: Optional[int] = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    sku: str = Field(index=True)
    name: str
    cost_price: float
    sell_price: float


class SaleLine(SQLModel, table=True):
    __tablename__ = "sale_line"
    id: Optional[int] = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    upload_id: int = Field(foreign_key="upload.id", index=True)
    date: str = Field(index=True)
    hour: int
    transaction_id: str = Field(index=True)
    sku: str = Field(index=True)
    qty: int
    unit_price: float


class BundleSuggestion(SQLModel, table=True):
    __tablename__ = "bundle_suggestion"
    id: Optional[int] = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    sku_a: str
    sku_b: str
    transactions_with_both: int
    transactions_with_a: int
    transactions_with_b: int
    total_transactions: int
    confidence: float
    lift: float
    separate_price: float
    separate_cost: float
    suggested_price: float
    suggested_margin_pct: float
    margin_floor_pct: float
    status: str = Field(default="pending")
    approved_price: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
