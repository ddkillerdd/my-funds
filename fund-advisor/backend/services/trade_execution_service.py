"""trade_execution_service.py — 实际操作记录 (RFC-020 块C).

提供:
  - record_manual(db, report_id, fund_code, actual_action, actual_amount, note)
    用户在前端回填"我怎么操作的", 自动附带该报告对该基金的建议(动作/金额)做对照。
  - record_from_diff(db, report_id, fund_code, actual_amount)   (预留 diff 自动比对)
  - list_by_report / list_recent
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from backend.models.trade_execution import TradeExecution
from backend.models.advisor_report import AdvisorReport

logger = logging.getLogger("fund.trade_execution")

# 实际动作枚举(映射到中文标签)
ACTION_LABELS = {
    "same_as_suggest": "照做",
    "increase": "加仓",
    "reduce": "减仓",
    "none": "未操作",
    "reversed": "反向",
}


def _load_suggestion(db: Session, report_id: int, fund_code: str) -> Optional[dict]:
    """从已保存的 advisor_report 里取该基金的建议动作/金额(供对照)。"""
    report = db.query(AdvisorReport).filter(AdvisorReport.id == report_id).first()
    if not report:
        return None
    import json
    try:
        data = json.loads(report.report_json)
    except Exception:  # noqa: BLE001
        return None
    for a in (data.get("actions") or []):
        if a.get("fund_code") == fund_code:
            return {
                "action": a.get("action"),
                "action_label": a.get("action_label"),
                "target_weight_pct": a.get("target_weight_pct"),
                "action_amount": a.get("action_amount"),
            }
    # 兜底: 从 holdings_health 取
    for h in (data.get("holdings_health") or []):
        if h.get("fund_code") == fund_code:
            return {
                "action": h.get("suggestion"),
                "action_label": h.get("suggestion_label"),
                "target_weight_pct": h.get("target_weight_pct"),
                "action_amount": h.get("action_amount"),
            }
    return None


def record_manual(
    db: Session,
    report_id: int,
    report_date: str,
    fund_code: str,
    fund_name: str,
    actual_action: str,
    actual_amount: Optional[float] = None,
    note: Optional[str] = None,
) -> TradeExecution:
    """记录一条用户实际操作(manual 来源)。若该报告同基金已有记录则覆盖更新。"""
    sug = _load_suggestion(db, report_id, fund_code) or {}
    existing = (
        db.query(TradeExecution)
        .filter(
            TradeExecution.report_id == report_id,
            TradeExecution.fund_code == fund_code,
        )
        .first()
    )
    label = ACTION_LABELS.get(actual_action, actual_action)
    if existing is None:
        row = TradeExecution(
            report_id=report_id,
            report_date=report_date,
            fund_code=fund_code,
            fund_name=fund_name,
            suggested_action=sug.get("action"),
            suggested_action_label=sug.get("action_label"),
            suggested_weight_pct=sug.get("target_weight_pct"),
            suggested_amount=sug.get("action_amount"),
            actual_action=actual_action,
            actual_action_label=label,
            actual_amount=actual_amount,
            source="manual",
            note=note,
        )
        db.add(row)
    else:
        existing.actual_action = actual_action
        existing.actual_action_label = label
        existing.actual_amount = actual_amount
        existing.fund_name = fund_name
        existing.note = note
        # 尽量补建议(若之前为空)
        existing.suggested_action = existing.suggested_action or sug.get("action")
        existing.suggested_action_label = existing.suggested_action_label or sug.get("action_label")
        existing.suggested_weight_pct = existing.suggested_weight_pct or sug.get("target_weight_pct")
        existing.suggested_amount = existing.suggested_amount if existing.suggested_amount is not None else sug.get("action_amount")
        row = existing
    db.commit()
    db.refresh(row)
    return row


def list_by_report(db: Session, report_id: int):
    rows = (
        db.query(TradeExecution)
        .filter(TradeExecution.report_id == report_id)
        .order_by(desc(TradeExecution.id))
        .all()
    )
    return [r.to_dict() for r in rows]


def list_recent(db: Session, limit: int = 50):
    rows = db.query(TradeExecution).order_by(desc(TradeExecution.id)).limit(limit).all()
    return [r.to_dict() for r in rows]
