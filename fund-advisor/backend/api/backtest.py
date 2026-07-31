"""Backtest & adaptive-learning API endpoints (RFC-012)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.backtest import BacktestStats

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats", response_model=BacktestStats)
def backtest_stats(db: Session = Depends(get_db)):
    """回测准确率统计：命中率、分动作、因子命中率、最近建议。"""
    from backend.services.backtest_service import BacktestService
    return BacktestService(db).get_stats()


@router.post("/validate")
def backtest_validate(db: Session = Depends(get_db)):
    """手动触发：验证所有到期(pending)的建议（抓最新净值+沪深300）。

    对应"手动触发适应"（RFC-012 三段式）中的验证步骤。
    """
    from backend.services.backtest_service import BacktestService
    n = BacktestService(db).validate_due()
    return {"validated": n, "message": f"已验证 {n} 条到期建议"}


@router.post("/adapt")
def backtest_adapt(db: Session = Depends(get_db)):
    """手动触发：运行在线学习适应（重算因子/动作命中率，校准置信度）。

    对应"手动触发适应"中收紧置信度/视角权重的步骤。
    """
    from backend.services.backtest_service import BacktestService
    svc = BacktestService(db)
    svc.validate_due()
    n = svc.refresh_hit_rates(rolling_window=20)
    fb = svc.get_feedback()
    return {
        "adapted_buckets": n,
        "has_evidence": fb.has_evidence,
        "prompt_hint": fb.prompt_hint,
        "action_hit_rates": fb.action_hit_rates,
    }
