from sqlmodel import SQLModel, Field
from sqlalchemy import BigInteger, Column, UniqueConstraint
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


class LiveEvent(SQLModel, table=True):
    """One thing that happened in a shop: a visitor came in, or a bill was rung.

    The append-only source of truth for live mode. The live rows in
    ``hourly_data`` and ``sale_line`` are derived from these and can always be
    rebuilt from them, so the dashboard and the bundle engine cannot disagree.
    """
    __tablename__ = "live_event"
    id: Optional[int] = Field(default=None, primary_key=True)
    #: Idempotency key: a retried request with the same id is ignored.
    event_id: str = Field(index=True, unique=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    kind: str = Field(index=True)            # "visit" | "bill"
    source: str = "sim"                      # "sim" | "pos"
    #: Shop-local (IST) wall-clock time, naive -- the same clock as the
    #: date/hour strings in hourly_data. date and hour are copied out of it
    #: so a rollup is one indexed lookup.
    ts: datetime = Field(index=True)
    date: str = Field(index=True)            # YYYY-MM-DD, IST
    hour: int
    #: Bills only. Integer paise, never float.
    amount_paise: int = 0
    #: Bills only: JSON list of {"sku", "qty", "unit_price_paise"}.
    lines: str = "[]"


class AlertChat(SQLModel, table=True):
    """A Telegram chat that gets a shop's alerts -- the owner's phone, or a
    group with the staff in it. A shop can have several."""
    __tablename__ = "alert_chat"
    __table_args__ = (UniqueConstraint("store_id", "chat_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    #: Telegram ids do not fit in 32 bits (groups are -100xxxxxxxxxx).
    chat_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    #: "Amartya" or the group's name, so the page can say who is connected.
    title: str = ""
    #: Also send a short update after every trading hour, not just alerts.
    hourly: bool = False
    linked_at: datetime = Field(default_factory=utc_now)


class AlertLinkCode(SQLModel, table=True):
    """A one-time code that ties a Telegram chat to a shop.

    The shop's page shows a link that opens the bot with this code; the bot
    sees it in "/start <code>" and links whoever sent it. Short-lived, so a
    code seen over someone's shoulder is useless by the time they try it.
    """
    __tablename__ = "alert_link_code"
    code: str = Field(primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    expires_at: datetime


class AlertSent(SQLModel, table=True):
    """Every alert raised for a shop, delivered or not.

    Doubles as the de-duplication key -- (store, kind, key) is unique, so the
    same hour is never reported twice, even across restarts -- and as the
    feed on the alerts page, which works without Telegram set up at all.
    """
    __tablename__ = "alert_sent"
    __table_args__ = (UniqueConstraint("store_id", "kind", "key"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    kind: str                       # "conversion_drop" | "behind_pace" | "day_summary"
    key: str                        # e.g. "2026-09-30" or "2026-09-30T14"
    text: str
    #: The shop clock when it was raised (IST, naive), which is ahead of the
    #: real clock while fast-forwarding.
    shop_time: datetime
    #: How many chats it reached; 0 when Telegram is not set up.
    delivered: int = 0
    created_at: datetime = Field(default_factory=utc_now)
