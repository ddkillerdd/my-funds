"""Holding schemas for API request/response."""

from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import date, datetime
from typing import Optional


class HoldingResponse(BaseModel):
    id: int
    fund_code: str
    fund_name: str
    share_type: Optional[str] = None
    management_company: Optional[str] = None
    platform: str
    fund_account: str
    trade_account: str
    shares: Decimal
    share_date: date
    nav_on_import: Optional[Decimal] = None
    nav_date: Optional[date] = None
    cost_nav: Optional[Decimal] = None
    market_value: Optional[Decimal] = None
    currency: str = "人民币"
    dividend_mode: Optional[str] = None
    status: int = 1
    source_type: str = "legacy"
    # Joined from funds table
    latest_nav: Optional[Decimal] = None
    latest_nav_date: Optional[date] = None
    nav_change_pct: Optional[Decimal] = None
    current_market_value: Optional[Decimal] = None
    daily_pnl: Optional[Decimal] = None
    total_pnl: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class HoldingCostUpdate(BaseModel):
    cost_nav: Decimal


class HoldingsByPlatformResponse(BaseModel):
    platform: str
    count: int
    total_market_value: Optional[Decimal] = None
    holdings: list[HoldingResponse] = []


class HoldingCreate(BaseModel):
    """Schema for creating a new manual holding entry."""
    fund_code: str
    fund_name: str
    share_type: Optional[str] = "前收费"
    management_company: Optional[str] = None
    platform: str
    fund_account: Optional[str] = None
    trade_account: Optional[str] = None
    shares: Decimal
    share_date: date
    nav_on_import: Optional[Decimal] = None
    cost_nav: Optional[Decimal] = None
    market_value: Optional[Decimal] = None
    currency: str = "人民币"
    dividend_mode: Optional[str] = None


class HoldingDeleteResponse(BaseModel):
    id: int
    fund_code: str
    fund_name: str
    status: str = "deleted"


class HoldingChangeRequest(BaseModel):
    """RFC-011: Record an add/increase or reduce/decrease operation by RMB amount.

    Add (increase): shares += amount/nav, and recompute average cost_nav (B scheme).
    Reduce (decrease): shares -= amount/nav; cost_nav unchanged; to 0 => clear.
    """
    change_type: str  # "increase" | "decrease"
    amount: Decimal    # RMB amount invested/redeemed this operation
    cost_nav_input: Optional[Decimal] = None  # actual buy price; default = latest nav
    note: Optional[str] = None
    business_date: Optional[date] = None


class HoldingChangeResponse(BaseModel):
    """Result of a holding change operation."""
    holding: HoldingResponse
    change: dict
    message: str = ""


# ---------- Simple Import (RFC-002) ----------


class SimpleImportRecord(BaseModel):
    """Single record for simple import — just fund_code + market_value."""
    fund_code: str
    market_value: Decimal
    platform: str = "支付宝"
    share_date: date = Field(default_factory=date.today)


class SimpleImportRequest(BaseModel):
    """Batch request for simple import."""
    records: list[SimpleImportRecord]


class SimpleImportResult(BaseModel):
    """Result of a simple import batch."""
    total: int = 0
    success: int = 0
    errors: list[dict] = Field(default_factory=list)
    details: list[HoldingResponse] = Field(default_factory=list)


class SimpleImportPreviewRequest(BaseModel):
    """快捷导入预览请求，不触发持久化。"""
    fund_code: str
    market_value: Decimal
    platform: str
    share_date: date


class SimpleImportPreviewResponse(BaseModel):
    """快捷导入预览结果。"""
    fund_code: str
    platform: str
    share_date: date
    fund_name: str
    latest_nav: Decimal
    latest_nav_date: Optional[date] = None
    estimated_shares: Decimal
