"""Simulator API endpoints (RFC-016: 组合策略回测 + 盈利能力 + 优化建议)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.simulator import (
    SimulationRequest,
    SimulationResponse,
    SimFundOptionOut,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/run", response_model=SimulationResponse,
             summary="组合策略回测(盈利能力 + 优化建议)")
def simulator_run(
    req: SimulationRequest,
    db: Session = Depends(get_db),
) -> SimulationResponse:
    """对用户自定义的基金组合 + 初始成本做多窗口点内策略回放,
    产出每日净值/盈亏趋势, 并给出盈利判定与优化建议。
    纯量化(RFC-016 Simulator), 零 LLM, 秒级完成。
    """
    from backend.services.simulator_service import SimulatorService
    data = SimulatorService(db).run(
        funds_in=[f.model_dump() for f in req.funds],
        initial_amount=req.initial_amount,
        windows=req.windows,
        warmup=req.warmup,
        target_vol=req.target_vol,
        friction_band_pp=req.friction_band_pp,
    )
    return SimulationResponse(**data)


@router.get("/funds", response_model=list[SimFundOptionOut],
            summary="回测可选基金列表")
def simulator_funds(
    db: Session = Depends(get_db),
) -> list:
    """返回可参与回测的基金(名称/最新净值/历史天数/是否可回测)。"""
    from backend.services.simulator_service import SimulatorService
    return SimulatorService(db).list_fund_options()
