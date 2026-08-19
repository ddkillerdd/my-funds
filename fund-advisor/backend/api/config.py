"""config.py — 全局配置读写 API (RFC-020 总资金).

提供:
  GET  /api/config/total-capital   读取当前生效总资金(可能 null)
  PUT  /api/config/total-capital   设置总资金(前端可随时改, 下次分析生效)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.config_service import (
    get_available_capital,
    get_total_capital,
    set_available_capital,
    set_total_capital,
)

router = APIRouter()


class CapitalIn(BaseModel):
    value: float = Field(..., gt=0, description="总资金(元), 必须>0")
    note: Optional[str] = None


@router.get("/total-capital", summary="读取当前生效总资金")
def read_total_capital(db: Session = Depends(get_db)):
    try:
        return {"total_capital": get_total_capital(db), "key": "total_capital_rmb"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")


@router.put("/total-capital", summary="设置总资金(前端可调)")
def update_total_capital(body: CapitalIn, db: Session = Depends(get_db)):
    try:
        set_total_capital(db, body.value, body.note)
        return {"ok": True, "total_capital": body.value}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")


@router.get("/available-capital", summary="读取可用增量资金(RFC-021)")
def read_available_capital(db: Session = Depends(get_db)):
    try:
        return {"available_capital": get_available_capital(db), "key": "available_capital_rmb"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")


@router.put("/available-capital", summary="设置可用增量资金(RFC-021)")
def update_available_capital(body: CapitalIn, db: Session = Depends(get_db)):
    try:
        set_available_capital(db, body.value, body.note)
        return {"ok": True, "available_capital": body.value}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")
