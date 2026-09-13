"""trade_execution.py — 建议执行反馈 API (RFC-020 块C).

提供:
  POST /api/trade-execution/record        回填建议执行分类
  GET  /api/trade-execution/report/{report_id}   某报告下所有建议反馈
  GET  /api/trade-execution/recent        最近建议反馈(默认50条)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.trade_execution_service import (
    record_manual,
    list_by_report,
    list_recent,
)

router = APIRouter()


SAFETY_RESPONSE = {
    "record_scope": "advice_feedback_only",
    "holdings_updated": False,
    "cash_updated": False,
    "settlement_recorded": False,
    "requires_trade_confirmation": True,
}


def _with_safety_contract(payload: dict) -> dict:
    """为所有反馈接口响应追加固定安全合同。"""
    return {**payload, **SAFETY_RESPONSE}


class TradeExecIn(BaseModel):
    report_id: int = Field(..., gt=0, description="关联 advisor_report.id")
    report_date: str = Field(..., description="报告日期 YYYY-MM-DD")
    fund_code: str = Field(..., min_length=1, description="基金代码")
    fund_name: Optional[str] = None
    actual_action: str = Field(..., description="same_as_suggest/increase/reduce/none/reversed")
    actual_amount: Optional[float] = Field(None, description="必须为空；本入口不记录成交金额")
    note: Optional[str] = None


@router.post("/record", summary="记录建议执行反馈(不更新真实持仓/现金)")
def create_record(body: TradeExecIn, db: Session = Depends(get_db)):
    try:
        row = record_manual(
            db,
            report_id=body.report_id,
            report_date=body.report_date,
            fund_code=body.fund_code,
            fund_name=body.fund_name or body.fund_code,
            actual_action=body.actual_action,
            actual_amount=body.actual_amount,
            note=body.note,
        )
        return _with_safety_contract({"ok": True, "record": row.to_dict()})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")


@router.get("/report/{report_id}", summary="某报告的所有建议执行反馈")
def get_by_report(report_id: int, db: Session = Depends(get_db)):
    return _with_safety_contract({"report_id": report_id, "records": list_by_report(db, report_id)})


@router.get("/recent", summary="最近建议执行反馈")
def get_recent(limit: int = 50, db: Session = Depends(get_db)):
    return _with_safety_contract({"records": list_recent(db, limit=min(limit, 200))})
