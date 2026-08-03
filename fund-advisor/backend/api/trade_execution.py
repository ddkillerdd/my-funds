"""trade_execution.py — 实际操作记录 API (RFC-020 块C).

提供:
  POST /api/trade-execution/record        回填"我怎么操作的"
  GET  /api/trade-execution/report/{report_id}   某报告下所有实际操作记录
  GET  /api/trade-execution/recent        最近实际操作记录(默认50条)
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


class TradeExecIn(BaseModel):
    report_id: int = Field(..., gt=0, description="关联 advisor_report.id")
    report_date: str = Field(..., description="报告日期 YYYY-MM-DD")
    fund_code: str = Field(..., min_length=1, description="基金代码")
    fund_name: Optional[str] = None
    actual_action: str = Field(..., description="same_as_suggest/increase/reduce/none/reversed")
    actual_amount: Optional[float] = Field(None, description="实际操作金额(元)")
    note: Optional[str] = None


@router.post("/record", summary="记录用户实际操作(前端回填)")
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
        return {"ok": True, "record": row.to_dict()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")


@router.get("/report/{report_id}", summary="某报告的所有实际操作记录")
def get_by_report(report_id: int, db: Session = Depends(get_db)):
    return {"report_id": report_id, "records": list_by_report(db, report_id)}


@router.get("/recent", summary="最近实际操作记录")
def get_recent(limit: int = 50, db: Session = Depends(get_db)):
    return {"records": list_recent(db, limit=min(limit, 200))}
