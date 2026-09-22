"""把用户确认的资金与操作频率规则落实为确定性程序门禁。"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from math import isfinite
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from backend.models.trade_execution import TradeExecution


DAILY_BUY_LIMIT_RMB = 20.0
MONTHLY_BUY_LIMIT_RMB = 200.0
DECISION_TIME = "14:00"
_BUY_ACTIONS = {"buy", "add", "increase"}
_GOOD_QUALITY = {"good", "adequate", "良好", "充足"}
_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _to_finite_float(value, default: float = 0.0) -> float:
    """把可能为空或异常的金额转成有限浮点数。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _field(item, name: str, default=None):
    """同时读取 ORM 对象和测试用字典字段。"""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _previous_weekday(day: date) -> date:
    """返回上一个周一至周五日期；节假日仍由外部交易日门禁负责。"""
    previous = day - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


def _fund_quality_map(report: dict) -> dict[str, dict]:
    """提取逐基金量化数据质量和长期收益字段。"""
    result = {}
    for item in report.get("per_fund_diagnosis") or []:
        if not isinstance(item, dict) or not item.get("fund_code"):
            continue
        quant = item.get("quant") or item.get("quant_indicator") or {}
        result[str(item["fund_code"])] = quant if isinstance(quant, dict) else {}
    return result


def _global_data_ready(report: dict) -> tuple[bool, list[str]]:
    """检查报告是否足以生成可执行金额，任何降级均失败关闭。"""
    reasons = []
    degradation = report.get("degradation") or {}
    completeness = report.get("completeness") or {}
    if bool(degradation.get("any")):
        reasons.append("analysis_degraded")
    quality = str(completeness.get("data_quality") or "unknown").strip().lower()
    if quality not in _GOOD_QUALITY:
        reasons.append("report_data_quality_not_ready")
    return not reasons, reasons


def _strict_cooldown_exception(report: dict, action: dict, quality_map: dict[str, dict]) -> bool:
    """仅在实时超跌且长期收益为正、数据完整时放宽一次连续交易限制。"""
    code = str(action.get("fund_code") or "")
    intraday = (report.get("intraday_view") or {}).get(code) or {}
    quant = quality_map.get(code) or {}
    quality = str(quant.get("data_quality") or "unknown").strip().lower()
    annual_return = _to_finite_float(quant.get("annual_return"), default=float("-inf"))
    return bool(
        quality in _GOOD_QUALITY
        and intraday.get("decision_live") is True
        and intraday.get("realtime_ok") is True
        and intraday.get("signal") == "oversold"
        and annual_return > 0
    )


def _history_budget(executions: Iterable, today: date) -> dict:
    """按用户回填的实际成交金额计算今日、本月买入额和最近买入日。"""
    daily_spent = 0.0
    monthly_spent = 0.0
    buy_dates = []
    for row in executions:
        amount = _to_finite_float(_field(row, "actual_amount"), 0.0)
        if amount <= 0:
            continue
        raw_date = str(_field(row, "report_date", ""))
        try:
            trade_day = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if trade_day == today:
            daily_spent += amount
        if trade_day.year == today.year and trade_day.month == today.month and trade_day <= today:
            monthly_spent += amount
        if trade_day < today:
            buy_dates.append(trade_day)
    return {
        "daily_spent": round(daily_spent, 2),
        "monthly_spent": round(monthly_spent, 2),
        "last_buy_date": max(buy_dates) if buy_dates else None,
    }


def apply_execution_policy(
    report: dict,
    executions: Iterable = (),
    today: Optional[date] = None,
    daily_limit: float = DAILY_BUY_LIMIT_RMB,
    monthly_limit: float = MONTHLY_BUY_LIMIT_RMB,
    decision_time: str = DECISION_TIME,
) -> dict:
    """限制报告金额：日20、月200、单日一只及相邻交易日冷却。"""
    target_day = today or date.today()
    result = deepcopy(report)
    actions = result.get("actions") or []
    quality_map = _fund_quality_map(result)
    data_ready, global_reasons = _global_data_ready(result)
    budget = _history_budget(executions, target_day)
    daily_limit = max(0.0, _to_finite_float(daily_limit, DAILY_BUY_LIMIT_RMB))
    monthly_limit = max(0.0, _to_finite_float(monthly_limit, MONTHLY_BUY_LIMIT_RMB))
    daily_remaining = max(0.0, daily_limit - budget["daily_spent"])
    monthly_remaining = max(0.0, monthly_limit - budget["monthly_spent"])
    last_buy_date = budget["last_buy_date"]
    cooldown_active = last_buy_date == _previous_weekday(target_day)

    positive_actions = []
    for action in actions:
        raw_amount = _to_finite_float(action.get("action_amount"), 0.0)
        action["raw_action_amount"] = raw_amount
        action["policy_status"] = "unchanged"
        action["policy_reasons"] = []
        if not data_ready and raw_amount != 0:
            action["action_amount"] = 0.0
            action["policy_status"] = "blocked"
            action["policy_reasons"] = list(global_reasons)
            continue
        if raw_amount > 0 and str(action.get("action") or "") in _BUY_ACTIONS:
            positive_actions.append(action)

    selected = None
    if data_ready and positive_actions:
        selected = max(
            positive_actions,
            key=lambda item: (
                _PRIORITY_RANK.get(str(item.get("priority") or "low"), 0),
                _to_finite_float(item.get("raw_action_amount"), 0.0),
                str(item.get("fund_code") or ""),
            ),
        )

    for action in positive_actions:
        if action is not selected:
            action["action_amount"] = 0.0
            action["policy_status"] = "blocked"
            action["policy_reasons"] = ["single_fund_daily_limit"]
            continue
        exception = _strict_cooldown_exception(result, action, quality_map)
        action["cooldown_exception"] = exception
        reasons = []
        if daily_remaining <= 0:
            reasons.append("daily_buy_limit_reached")
        if monthly_remaining <= 0:
            reasons.append("monthly_buy_limit_reached")
        if cooldown_active and not exception:
            reasons.append("consecutive_trading_day_cooldown")
        if reasons:
            action["action_amount"] = 0.0
            action["policy_status"] = "blocked"
            action["policy_reasons"] = reasons
            continue
        raw_amount = _to_finite_float(action.get("raw_action_amount"), 0.0)
        allowed = round(min(raw_amount, daily_remaining, monthly_remaining), 2)
        action["action_amount"] = allowed
        action["policy_status"] = "allowed" if allowed == raw_amount else "capped"
        action["policy_reasons"] = [] if allowed == raw_amount else ["budget_cap_applied"]

    result["execution_policy"] = {
        "decision_time": decision_time,
        "timezone": "Asia/Shanghai",
        "daily_buy_limit_rmb": daily_limit,
        "monthly_buy_limit_rmb": monthly_limit,
        "daily_buy_spent_rmb": budget["daily_spent"],
        "monthly_buy_spent_rmb": budget["monthly_spent"],
        "daily_buy_remaining_rmb": round(daily_remaining, 2),
        "monthly_buy_remaining_rmb": round(monthly_remaining, 2),
        "single_fund_per_day": True,
        "cooldown_active": cooldown_active,
        "last_buy_date": last_buy_date.isoformat() if last_buy_date else None,
        "strict_exception_rule": "实时超跌+长期年化收益为正+逐基金及整报告数据完整",
        "data_quality_ready": data_ready,
        "global_gate_reasons": global_reasons,
        "actual_amount_source": "trade_execution.actual_amount",
        "holiday_guard_owner": "OpenClaw交易日门禁",
    }
    return result


def apply_execution_policy_from_db(
    db: Session,
    report: dict,
    today: Optional[date] = None,
    daily_limit: float = DAILY_BUY_LIMIT_RMB,
    monthly_limit: float = MONTHLY_BUY_LIMIT_RMB,
    decision_time: str = DECISION_TIME,
) -> dict:
    """读取本月实际操作记录后应用确定性执行门禁。"""
    target_day = today or date.today()
    month_start = target_day.replace(day=1).isoformat()
    rows = (
        db.query(TradeExecution)
        .filter(
            TradeExecution.report_date >= month_start,
            TradeExecution.report_date <= target_day.isoformat(),
        )
        .all()
    )
    return apply_execution_policy(
        report,
        rows,
        today=target_day,
        daily_limit=daily_limit,
        monthly_limit=monthly_limit,
        decision_time=decision_time,
    )


def fail_closed_execution_policy(report: dict, reason: str = "policy_unavailable") -> dict:
    """门禁计算异常时把所有非零建议金额归零，避免绕过安全规则。"""
    result = deepcopy(report)
    for action in result.get("actions") or []:
        raw_amount = _to_finite_float(action.get("action_amount"), 0.0)
        action["raw_action_amount"] = raw_amount
        if raw_amount != 0:
            action["action_amount"] = 0.0
            action["policy_status"] = "blocked"
            action["policy_reasons"] = [reason]
    result["execution_policy"] = {
        "decision_time": DECISION_TIME,
        "timezone": "Asia/Shanghai",
        "daily_buy_limit_rmb": DAILY_BUY_LIMIT_RMB,
        "monthly_buy_limit_rmb": MONTHLY_BUY_LIMIT_RMB,
        "data_quality_ready": False,
        "global_gate_reasons": [reason],
        "fail_closed": True,
    }
    return result
