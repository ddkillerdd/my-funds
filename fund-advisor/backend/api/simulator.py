"""Simulator API endpoints (RFC-016: 组合策略回测 + 盈利能力 + 优化建议)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/tmp-funds", summary="临时拉取的基金(仅本次模拟, 打标记)")
def simulator_tmp_funds(db: Session = Depends(get_db)):
    """列出所有临时拉取、可供回测的基金(存于临时表, 不污染主库)。"""
    from backend.services.simulator_service import SimulatorService
    return SimulatorService(db).list_tmp_funds()


@router.post("/fetch-remote", summary="拉取任意基金历史净值(临时, 仅本次模拟)")
async def simulator_fetch_remote(
    fund_code: str,
    fund_name: str = "",
    db: Session = Depends(get_db),
):
    """输入任意基金代码, 从天天基金拉取约 2 年历史净值, 存入临时表打标。
    
    - 不写入 funds / fund_nav_history 主表, 不影响持仓分析。
    - 回测用完后可调用 /cleanup-tmp 清理, 避免冗余。
    """
    from backend.services.simulator_service import SimulatorService
    try:
        return await SimulatorService(db).fetch_remote_fund(fund_code, fund_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("fetch_remote_fund failed")
        raise HTTPException(status_code=502, detail=f"拉取失败: {e}")


@router.post("/cleanup-tmp", summary="清理临时基金(用后即删)")
def simulator_cleanup_tmp(
    keep_days: int = 1,
    db: Session = Depends(get_db),
):
    """清理临时拉取的基金(默认清理超过 1 天未使用的)。返回清理条数。"""
    from backend.services.simulator_service import SimulatorService
    n = SimulatorService(db).cleanup_tmp_funds(keep_days=keep_days)
    return {"cleaned": n, "message": f"已清理 {n} 条临时基金"}
