"""Wire format for the pooling API.

Every monetary field is an integer number of paise. Formatting to rupees is
the frontend's job -- sending floats over the wire would reintroduce exactly
the rounding error the domain layer works to avoid.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class TierOut(BaseModel):
    min_qty: int
    max_qty: Optional[int] = None
    unit_price: int
    label: str


class StoreLineOut(BaseModel):
    store: str
    qty: int
    cost_alone: int
    payable: int
    savings: int


class PoolProductOut(BaseModel):
    sku: str
    name: str
    supplier_id: str
    price_list_version: str
    total_qty: int
    pooled_unit_price: int
    tier_label: str
    units_to_next_tier: Optional[int] = None
    next_tier_unit_price: Optional[int] = None
    invoice_total: int
    total_savings: int
    tiers: list[TierOut]
    lines: list[StoreLineOut]


class PoolStoreOut(BaseModel):
    store: str
    cost_alone: int
    payable: int
    savings: int
    savings_pct: float


class PoolOut(BaseModel):
    code: str
    name: str
    status: str
    strategy: str
    rotation: int
    closes_at: Optional[str] = None
    invoice_total: int
    total_savings: int
    products: list[PoolProductOut]
    stores: list[PoolStoreOut]


class PoolSummaryOut(BaseModel):
    code: str
    name: str
    status: str
    store_count: int
    total_savings: int


class PlaceOrderIn(BaseModel):
    #: Defaults to the logged-in shop; naming any other shop is refused.
    store_id: Optional[str] = None
    sku: str
    qty: int


class WithdrawIn(BaseModel):
    store_id: Optional[str] = None
    sku: Optional[str] = None


class PoolEventOut(BaseModel):
    actor: str
    kind: str
    detail: str
    created_at: str
