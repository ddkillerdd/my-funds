"""Plan API endpoints (RFC-018: 长期投资方案中心).

六大模块: 基金池 / AI荐基 / 配比 / 回测验证 / 分批 / 确认建仓。
端点:
  POST /plan/pool                    温启动基金池
  GET  /plan/pool                    候选池列表(可筛类型/风格/标签/关键词)
  POST /plan/recommend               AI荐基(budget, risk) -> Top N + 理由
  POST /plan/allocate                配比(picks, risk) -> weights
  POST /plan/backtest                回测验证(异步) -> task_id
  GET  /plan/backtest/tasks/{id}     轮询回测结果
  POST /plan                           创建计划(draft, 存配比+AI解读)
  POST /plan/{id}/tranches            生成分批批次
  POST /plan/{id}/confirm             确认建仓(执行 N 批)
  GET  /plan                         我的计划列表
  GET  /plan/{id}                    计划详情
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ─────────────────────────────────────────
class RecommendRequest(BaseModel):
    budget: float = Field(100.0, gt=0, description="固定预算")
    risk_profile: str = "balanced"
    fund_types: Optional[List[str]] = None


class AllocateRequest(BaseModel):
    picks: List[dict]
    risk_profile: str = "balanced"


class PlanCreateRequest(BaseModel):
    total_budget: float = Field(..., gt=0)
    risk_profile: str = "balanced"
    name: str = "我的入场计划"
    target_allocation: dict
    ai_summary: Optional[str] = None


class BacktestRequest(BaseModel):
    funds: List[dict]
    windows: Optional[List[int]] = None
    target_vol: float = 0.15
    friction_band_pp: float = 5.0


class TrancheRequest(BaseModel):
    fund_windows: Optional[dict] = None
    total_weeks: int = 16
    interval_weeks: int = 2


class ConfirmRequest(BaseModel):
    execute_tranches: int = 1


class FundTypeList(BaseModel):
    fund_types: Optional[List[str]] = None


# ── ① 基金池 ────────────────────────────────────────
@router.post("/pool", summary="温启动全市场基金候选池")
async def plan_pool_warmstart(
    pages: int = 5,
    db: Session = Depends(get_db),
):
    from backend.services.fund_pool import FundPoolService
    return await FundPoolService(db).warm_start(pages=pages)


@router.get("/pool", summary="候选池列表(可筛选)")
def plan_pool_list(
    fund_type: Optional[str] = None,
    style: Optional[str] = None,
    label: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    from backend.services.fund_pool import FundPoolService
    return {"items": FundPoolService(db).list_candidates(
        fund_type=fund_type, style=style, label=label, keyword=keyword, limit=limit
    ), "counts": FundPoolService(db).counts()}


@router.get("/pool/counts", summary="候选池统计")
def plan_pool_counts(db: Session = Depends(get_db)):
    from backend.services.fund_pool import FundPoolService
    return FundPoolService(db).counts()


# ── ② AI荐基 ────────────────────────────────────────
@router.post("/recommend", summary="AI荐基: 预算+风险 -> Top N + 理由")
async def plan_recommend(req: RecommendRequest, db: Session = Depends(get_db)):
    from backend.services.plan_recommender import PlanRecommenderService
    return await PlanRecommenderService(db).recommend(
        budget=req.budget, risk_profile=req.risk_profile, fund_types=req.fund_types
    )


# ── ③ 配比 ──────────────────────────────────────────
@router.post("/allocate", summary="智能配比: 选中基金 -> 权重(风控约束)")
def plan_allocate(req: AllocateRequest, db: Session = Depends(get_db)):
    from backend.services.plan_allocator import PlanAllocatorService
    return PlanAllocatorService(db).allocate(req.picks, risk_profile=req.risk_profile)


# ── ④ 回测验证(异步) ───────────────────────────────
@router.post("/backtest", summary="回测验证(异步提交, 返回 task_id)")
def plan_backtest_submit(req: BacktestRequest, db: Session = Depends(get_db)):
    from backend.services.plan_backtest import PlanBacktestService
    try:
        return PlanBacktestService(db).submit_backtest(
            funds=req.funds,
            windows=req.windows,
            target_vol=req.target_vol,
            friction_band_pp=req.friction_band_pp,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/backtest/tasks/{task_id}", summary="轮询回测任务结果")
def plan_backtest_status(task_id: str, db: Session = Depends(get_db)):
    from backend.services.plan_backtest import PlanBacktestService
    st = PlanBacktestService(db).task_status(task_id)
    if not st:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return st


# ── ⑤⑥ 计划 ────────────────────────────────────────
@router.post("", summary="创建投资计划(draft)")
def plan_create(req: PlanCreateRequest, db: Session = Depends(get_db)):
    from backend.services.plan import PlanService
    try:
        plan = PlanService(db).create_plan(
            total_budget=req.total_budget,
            risk_profile=req.risk_profile,
            name=req.name,
            target_allocation=req.target_allocation,
            ai_summary=req.ai_summary,
        )
        return plan.concise()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{plan_id}/tranches", summary="生成分批批次(100份)")
def plan_generate_tranches(plan_id: int, req: TrancheRequest, db: Session = Depends(get_db)):
    from backend.services.plan import PlanService
    try:
        return PlanService(db).generate_tranches(
            plan_id=plan_id,
            fund_windows=req.fund_windows,
            total_weeks=req.total_weeks,
            interval_weeks=req.interval_weeks,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{plan_id}/confirm", summary="确认入场 -> 建仓 + 计划启用")
def plan_confirm(plan_id: int, req: ConfirmRequest, db: Session = Depends(get_db)):
    from backend.services.plan import PlanService
    try:
        return PlanService(db).confirm_entry(plan_id, execute_tranches=req.execute_tranches)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", summary="我的计划列表")
def plan_list(status: Optional[str] = None, db: Session = Depends(get_db)):
    from backend.services.plan import PlanService
    return PlanService(db).list_plans(status=status)


@router.get("/{plan_id}", summary="计划详情")
def plan_detail(plan_id: int, db: Session = Depends(get_db)):
    from backend.services.plan import PlanService
    plan = PlanService(db).get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"计划 {plan_id} 不存在")
    return plan
