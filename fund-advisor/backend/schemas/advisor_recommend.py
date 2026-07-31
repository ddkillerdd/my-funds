"""Schemas for the recommendation endpoints (RFC-010: 择时 + 荐基)."""

from pydantic import BaseModel, Field
from typing import List, Optional


# ============================================================
#  入场择时 (recommend/timing)
# ============================================================

class TimingFactorOut(BaseModel):
    name: str
    value: Optional[float] = None
    score: float = 0.0
    evidence: str = ""


class TimingRequest(BaseModel):
    fund_code: str
    fund_name: Optional[str] = None
    playbook: str = "auto"   # value | trend | balanced | auto


class TimingResponse(BaseModel):
    fund_code: str = ""
    fund_name: str = ""
    recommendation: str = "wait"      # avoid | wait | staged_entry | buy_now | dca
    confidence_pct: float = 0.0
    action_label: str = ""
    risk_gate_status: str = "passed"  # passed | blocked
    risk_gate_reason: str = ""
    timing_factors: List[TimingFactorOut] = Field(default_factory=list)
    suggested_dca: Optional[dict] = None
    notes: List[str] = Field(default_factory=list)
    data_quality: str = "unknown"
    disclaimer_note: str = "仅供参考，不构成投资建议"
    error: Optional[str] = None


# ============================================================
#  荐基打分 (recommend/screen)
# ============================================================

class CandidateIn(BaseModel):
    fund_code: str
    fund_name: Optional[str] = None


class ScreenRequest(BaseModel):
    candidates: List[CandidateIn]
    budget_pct: float = 10.0
    top_n: int = 5
    portfolio_holdings_info: Optional[str] = None
    with_ai_explanation: bool = False
    use_current_portfolio: bool = True   # 用当前 DB 持仓做分散化参照


class FactorScoreOut(BaseModel):
    factor: str
    score: float
    evidence: str = ""
    weight: float = 0.0


class RecommendationOut(BaseModel):
    fund_code: str
    fund_name: str
    fund_type: str = ""
    total_score: float
    style_tag: str = "未知"
    correlation_with_portfolio: Optional[float] = None
    suggested_ratio_pct: float = 0.0
    timing_window: str = "wait"
    timing_score: float = 50.0
    factor_scores: List[FactorScoreOut] = Field(default_factory=list)
    ai_explanation: str = ""
    data_quality: str = "unknown"
    disclaimer_note: str = "仅供参考，不构成投资建议"


class ScreenResponse(BaseModel):
    candidates_scanned: int = 0
    portfolio_context: Optional[dict] = None
    recommendations: List[RecommendationOut] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    data_quality: str = "unknown"
    error: Optional[str] = None
