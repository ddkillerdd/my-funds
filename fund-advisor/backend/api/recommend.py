"""Recommendation API endpoints (RFC-010: 择时 + 荐基)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.advisor_recommend import (
    ScreenRequest,
    ScreenResponse,
    TimingRequest,
    TimingResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_MODEL = "deepseek-ai/deepseek-v4-flash"


@router.post("/timing", response_model=TimingResponse,
             summary="单基金入场择时")
def recommend_timing(
    req: TimingRequest,
    db: Session = Depends(get_db),
) -> TimingResponse:
    """对指定基金给出入场择时建议（现买/等待/分批建仓/定投）。纯量化，不涉 LLM。"""
    from backend.services.recommend_service import RecommendService
    data = RecommendService(db).get_timing(
        fund_code=req.fund_code,
        fund_name=req.fund_name,
        playbook=req.playbook,
    )
    return TimingResponse(**data)


@router.post("/screen", response_model=ScreenResponse,
             summary="候选基金池荐基打分")
def recommend_screen(
    req: ScreenRequest,
    db: Session = Depends(get_db),
) -> ScreenResponse:
    """对候选基金池做六因子荐基打分排序。可选 LLM 后置解读。"""
    from backend.services.recommend_service import RecommendService
    data = RecommendService(db).run_screen(
        candidates=[c.model_dump() for c in req.candidates],
        budget_pct=req.budget_pct,
        top_n=req.top_n,
        portfolio_holdings_info=req.portfolio_holdings_info,
        with_ai_explanation=req.with_ai_explanation,
        use_current_portfolio=req.use_current_portfolio,
    )
    return ScreenResponse(**data)
