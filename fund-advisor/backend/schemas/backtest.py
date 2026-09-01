"""Schemas for backtest / adaptive-learning API responses (RFC-012)."""

from pydantic import BaseModel
from decimal import Decimal
from datetime import date
from typing import Optional


class AdviceRecord(BaseModel):
    id: Optional[int] = None
    report_id: Optional[int] = None
    fund_code: str
    fund_name: Optional[str] = None
    action: str
    advice_date: date
    nav_at_advice: Optional[Decimal] = None
    change_pct: Optional[Decimal] = None
    status: str = "pending"
    validation_date: Optional[date] = None
    fund_change_pct: Optional[Decimal] = None
    benchmark_change_pct: Optional[Decimal] = None
    relative_return: Optional[Decimal] = None
    verdict: Optional[str] = None

    model_config = {"from_attributes": True}


class FactorHitRateOut(BaseModel):
    factor_key: str
    action_type: str
    total: int = 0
    hits: int = 0
    miss: int = 0
    hit_rate: Optional[Decimal] = None
    rolling_window: int = 20

    model_config = {"from_attributes": True}


class BacktestStats(BaseModel):
    total_advice: int = 0
    pending: int = 0
    validated: int = 0
    directional: int = 0
    hits: int = 0
    miss: int = 0
    neutral: int = 0
    hit_rate: Optional[Decimal] = None
    coverage: Decimal = Decimal("0")
    by_action: dict = {}
    factor_rates: list[FactorHitRateOut] = []
    recent_advice: list[AdviceRecord] = []


class FeedbackPayload(BaseModel):
    """What the integration layer returns to the analyzer for the next run."""
    view_feedback: dict = {}
    action_hit_rates: dict = {}
    prompt_hint: str = ""
    has_evidence: bool = False
