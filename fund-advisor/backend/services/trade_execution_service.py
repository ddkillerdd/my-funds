"""trade_execution_service.py — 建议执行反馈 (RFC-020 块C).

提供:
  - record_manual(db, report_id, fund_code, actual_action, actual_amount, note)
    用户在前端回填建议执行分类，自动附带该报告对该基金的建议做对照。
  - list_by_report / list_recent
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.models.trade_execution import TradeExecution
from backend.models.advisor_report import AdvisorReport

logger = logging.getLogger("fund.trade_execution")

# 建议执行反馈分类及中文标签。
ACTION_LABELS = {
    "same_as_suggest": "照做",
    "increase": "加仓",
    "reduce": "减仓",
    "none": "未操作",
    "reversed": "反向",
}
ALLOWED_ACTIONS = frozenset(ACTION_LABELS)


def _validate_feedback_input(
    report_date: str,
    fund_code: str,
    actual_action: str,
    actual_amount: Optional[float],
) -> None:
    """在任何数据库动作前校验建议执行反馈输入。"""
    if actual_action not in ALLOWED_ACTIONS:
        raise ValueError("actual_action 仅允许 same_as_suggest/increase/reduce/none/reversed")
    if actual_amount is not None:
        raise ValueError("actual_amount 必须为 null；建议反馈入口不记录成交金额")
    if not isinstance(report_date, str):
        raise ValueError("report_date 必须为严格 YYYY-MM-DD 日期")
    try:
        parsed = datetime.strptime(report_date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("report_date 必须为严格 YYYY-MM-DD 日期") from exc
    if parsed.strftime("%Y-%m-%d") != report_date:
        raise ValueError("report_date 必须为严格 YYYY-MM-DD 日期")
    if not isinstance(fund_code, str) or not fund_code.strip():
        raise ValueError("fund_code 不能为空")


def _suggestion_from_item(item: dict, *, health: bool = False) -> dict:
    """将报告中的一条建议转换为反馈对照字段。"""
    return {
        "action": item.get("suggestion" if health else "action"),
        "action_label": item.get("suggestion_label" if health else "action_label"),
        "target_weight_pct": item.get("target_weight_pct"),
        "action_amount": item.get("action_amount"),
    }


def _load_suggestion(db: Session, report_id: int, fund_code: str) -> dict:
    """从报告中唯一定位基金建议，拒绝缺失或无法消歧的候选。"""
    report = db.query(AdvisorReport).filter(AdvisorReport.id == report_id).first()
    if not report:
        raise ValueError(f"报告 {report_id} 不存在")
    try:
        data = json.loads(report.report_json)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"报告 {report_id} 数据异常") from exc
    if not isinstance(data, dict):
        raise ValueError(f"报告 {report_id} 数据异常")

    actions = [
        item for item in (data.get("actions") or [])
        if isinstance(item, dict) and item.get("fund_code") == fund_code
    ]
    if len(actions) > 1:
        raise ValueError("同一建议来源中基金重复，当前合同缺少平台/建议行标识，不能消歧")
    if len(actions) == 1:
        return _suggestion_from_item(actions[0])

    health_items = [
        item for item in (data.get("holdings_health") or [])
        if isinstance(item, dict) and item.get("fund_code") == fund_code
    ]
    if len(health_items) > 1:
        raise ValueError("同一建议来源中基金重复，当前合同缺少平台/建议行标识，不能消歧")
    if len(health_items) == 1:
        return _suggestion_from_item(health_items[0], health=True)
    raise ValueError(f"基金 {fund_code} 不在报告建议中")


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
    """记录建议执行分类反馈，不代表成交或结算。"""
    _validate_feedback_input(report_date, fund_code, actual_action, actual_amount)
    sug = _load_suggestion(db, report_id, fund_code)
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
    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise
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
