"""
adaptive.py — 自适应参数优化 API (RFC-017 · 甲方案·半自动模式 X)

前端"自适应"页调用: 发起 WFA 优化(异步) → 轮询状态 → 列出推荐(带样本外证据)
→ 用户点采纳/否决。仅 approved 进入生效配置, 未确认一律不影响实盘。
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.adaptive_service import AdaptiveService

router = APIRouter()


def _svc(db: Session) -> AdaptiveService:
    return AdaptiveService(db)


@router.post("/run", summary="异步发起一次自适应优化(WFA)")
def adaptive_run(
    fund_codes: Optional[List[str]] = Query(default=None, description="要参与的基金代码; 空=主库全部"),
    lookback_days: int = Query(default=600, ge=350, le=1300,
                               description="回看交易日数(建议 350~1300)"),
    tv_grid: Optional[List[float]] = Query(default=None, description="自定义 target_vol 网格"),
    fr_grid: Optional[List[int]] = Query(default=None, description="自定义 friction 网格"),
    db: Session = Depends(get_db),
):
    """发起 WFA。计算较慢, 返回 task_id, 前端轮询 /tasks/{id}。"""
    svc = _svc(db)
    try:
        return svc.submit_optimize(fund_codes=fund_codes, lookback_days=lookback_days,
                                   tv_grid=tv_grid, fr_grid=fr_grid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"发起失败: {e}")


@router.get("/tasks/{task_id}", summary="轮询异步任务状态")
def adaptive_task(task_id: str, db: Session = Depends(get_db)):
    st = _svc(db).task_status(task_id)
    if st is None:
        raise HTTPException(status_code=404, detail="任务不存在(可能已随重启清空)")
    return st


@router.get("/proposals", summary="列出自适应推荐")
def adaptive_proposals(
    status: Optional[str] = Query(default=None, description="pending/approved/rejected"),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    return _svc(db).list_proposals(status=status, limit=limit)


@router.post("/proposals/{proposal_id}/approve", summary="采纳推荐(写入生效配置)")
def adaptive_approve(proposal_id: int, note: str = "", db: Session = Depends(get_db)):
    try:
        return _svc(db).approve(proposal_id, note=note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/proposals/{proposal_id}/reject", summary="否决推荐")
def adaptive_reject(proposal_id: int, note: str = "", db: Session = Depends(get_db)):
    try:
        return _svc(db).reject(proposal_id, note=note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/overrides", summary="当前生效的策略参数")
def adaptive_overrides(db: Session = Depends(get_db)):
    return _svc(db).active_overrides()


@router.post("/overrides/{risk_class}/reset", summary="撤销某类生效参数(回退保守默认)")
def adaptive_reset(risk_class: str, db: Session = Depends(get_db)):
    if risk_class not in ("low", "medium", "high"):
        raise HTTPException(status_code=400, detail="risk_class 须为 low/medium/high")
    return _svc(db).reset_override(risk_class)
