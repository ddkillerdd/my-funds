"""确定性日报预览：仅渲染现有报告，不生成分析、不发送邮件、不写数据。"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from html import escape
import re

from backend.services.purchase_channel_service import SHANGHAI, decimal_value, plan_purchase


REASON_LABELS = {
    "legacy_report": "旧报告未包含渠道门禁，不作为当前下单依据",
    "stale_report": "报告不是当天生成、时间异常或已超过30分钟",
    "outside_decision_window": "已不在14:00至14:45决策时段，或不是工作日",
    "analysis_not_ready": "分析降级或数据质量不满足要求",
    "budget_not_rechecked": "未能重新核对跨平台实际支出和剩余预算",
    "policy_blocked": "原报告已被门禁拦截，预览不能恢复候选金额",
    "channel_unverified": "渠道、账户资格、费用或额度未通过复核",
    "multiple_buy_candidates": "出现多条正向建议，不符合单日单只规则",
    "redemption_fee_unverified": "赎回费及分笔持有期限尚未核验",
    "invalid_action": "基金代码、动作方向或金额异常",
    "daily_buy_limit_reached": "今日20元付款额度已用完",
    "monthly_buy_limit_reached": "本月200元付款额度已用完",
    "consecutive_trading_day_cooldown": "连续操作冷却尚未解除",
    "single_fund_daily_limit": "单日仅允许一只基金买入",
    "analysis_degraded": "原分析已降级，渠道确认不能解除",
    "purchase_channel_unverified": "账户可买性、费率或容量仍未通过核验",
}


def _created_in_shanghai(value: datetime) -> datetime:
    """数据库无时区时间按既有约定视为UTC，不信任模型自填的生成时间。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI)


def _global_reasons(analysis, created_at, clock, budget_rechecked):
    """在渠道复核前检查日期、时段、质量和原始门禁标记。"""
    policy = analysis.get("execution_policy") or {}
    reasons = []
    if policy.get("purchase_channel_gate") is not True:
        reasons.append("legacy_report")
    try:
        created = _created_in_shanghai(created_at)
        age = clock - created
        if created.date() != clock.date() or not timedelta(0) <= age <= timedelta(minutes=30):
            reasons.append("stale_report")
    except (AttributeError, TypeError, ValueError, OverflowError):
        reasons.append("stale_report")
    if clock.weekday() >= 5 or not time(14, 0) <= clock.time().replace(tzinfo=None) < time(14, 45):
        reasons.append("outside_decision_window")
    quality = str((analysis.get("completeness") or {}).get("data_quality") or "").lower()
    if (analysis.get("degradation") or {}).get("any") or quality not in {"good", "adequate", "良好", "充足"} or policy.get("data_quality_ready") is not True:
        reasons.append("analysis_not_ready")
    if not budget_rechecked:
        reasons.append("budget_not_rechecked")
    return reasons


def _delivery_action(action, global_reasons, clock, payment_cap, multiple_buys):
    """只从最终金额生成安全摘要，不读取或复活raw候选及自由文本操作理由。"""
    item = {
        "fund_code": str(action.get("fund_code") or ""),
        "fund_name": str(action.get("fund_name") or action.get("fund_code") or "未知基金"),
        "action": "none", "action_label": "不操作", "payment_rmb": 0.0,
        "estimated_fee_rmb": None, "estimated_net_investment_rmb": None,
        "reasons": list(global_reasons),
    }
    try:
        if isinstance(action.get("action_amount"), bool):
            raise ValueError("布尔值不是金额")
        raw = float(action.get("action_amount") or 0)
        amount = decimal_value(abs(raw))
    except (ValueError, TypeError, OverflowError):
        item["reasons"].append("invalid_action")
        return item
    if not re.fullmatch(r"\d{6}", item["fund_code"]):
        item["reasons"].append("invalid_action")
        return item
    if raw == 0 and action.get("policy_status") == "blocked":
        # 归零也必须解释原因，不把预算/渠道拦截静默显示成正常无操作。
        policy_reasons = action.get("policy_reasons")
        if not isinstance(policy_reasons, list) or not policy_reasons:
            policy_reasons = ["policy_blocked"]
        item["reasons"].extend(reason if isinstance(reason, str) and reason in REASON_LABELS else "policy_blocked" for reason in policy_reasons)
    if raw < 0:
        item["reasons"].append("redemption_fee_unverified")
    elif raw > 0:
        if action.get("action") not in {"buy", "add", "increase"}:
            item["reasons"].append("invalid_action")
        if action.get("policy_status") not in {"allowed", "capped"}:
            item["reasons"].append("policy_blocked")
        if multiple_buys:
            item["reasons"].append("multiple_buy_candidates")
        check = action.get("purchase_check")
        if not isinstance(check, dict) or check.get("status") != "checked":
            item["reasons"].append("channel_unverified")
        if not item["reasons"]:
            # 不自动恢复原始候选，也不放大报告金额；再次按当前预算和快照计算。
            fresh = plan_purchase(item["fund_code"], min(amount, payment_cap), [check], clock)
            if fresh["status"] == "checked":
                item.update(
                    action="buy", action_label="买入付款预览（需手动确认）",
                    payment_rmb=fresh["gross_payment_rmb"],
                    estimated_fee_rmb=fresh["estimated_fee_rmb"],
                    estimated_net_investment_rmb=fresh["estimated_net_investment_rmb"],
                    platform=fresh["platform"], payment_method=fresh["payment_method"],
                    subscription_fee_rate_pct=fresh["subscription_fee_rate_pct"],
                    observed_at=fresh["observed_at"], source=fresh["source"],
                )
            else:
                item["reasons"].append("channel_unverified")
    return item


def _render_html(report_id, clock, actions, global_reasons=()):
    """以手机可读卡片显示最终付款，转义所有动态文本且不插入模型自由HTML。"""
    esc = lambda value: escape(str(value), quote=True)
    cards = []
    for item in actions:
        reasons = "；".join(REASON_LABELS.get(reason, "未满足安全条件") for reason in dict.fromkeys(item["reasons"]))
        detail = esc(reasons or "无新增资金操作")
        if item["payment_rmb"] > 0:
            detail = (
                f"渠道：{esc(item['platform'])} · {esc(item['payment_method'])}<br>"
                f"总付款：{item['payment_rmb']:.2f}元（含申购费）<br>"
                f"申购费率：{item['subscription_fee_rate_pct']}% · 预计费用：{item['estimated_fee_rmb']:.2f}元<br>"
                f"预计净投入：{item['estimated_net_investment_rmb']:.2f}元<br>"
                f"证据时间：{esc(item['observed_at'])}<br>来源：{esc(item['source'])}"
            )
        cards.append(
            '<section style="border-left:4px solid #409eff;background:#f0f9ff;padding:14px;margin:12px 0;border-radius:6px;overflow-wrap:anywhere">'
            f"<h2 style='font-size:17px;margin:0 0 8px'>{esc(item['fund_name'])}（{esc(item['fund_code'])}）</h2>"
            f"<strong>{esc(item['action_label'])} · {item['payment_rmb']:.2f}元</strong><p style='margin-bottom:0'>{detail}</p></section>"
        )
    conclusion = "有待手动确认的付款预览" if any(item["payment_rmb"] > 0 for item in actions) else "今日不操作 · 0.00元"
    summary = "；".join(REASON_LABELS.get(reason, "未满足安全条件") for reason in dict.fromkeys(global_reasons))
    return (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="font-family:-apple-system,sans-serif;max-width:680px;margin:auto;padding:18px;color:#303133;line-height:1.7">'
        '<h1 style="text-align:center;color:#409eff;font-size:23px">持仓决策安全摘要</h1>'
        f"<p>日期：{clock.date().isoformat()} · 报告编号：{int(report_id)}</p><h2>{conclusion}</h2>"
        f"<p>{esc(summary)}</p>"
        '<p>日付款最多20元、月付款最多200元，所有平台合计且包含申购费。节假日仍须由原交易日门禁判断。</p>'
        + "".join(cards)
        + '<p>只展示代码门禁后的结果。不会把原始候选、目标仓位或模型自由文字当作下单指令。</p>'
        '<p>申购费比较不等于持有期总成本排名；已计入净值的管理、托管及销售服务费不重复扣除。实际费用、份额和净值以平台确认为准。</p>'
        '<p style="color:#909399">不自动交易、不预约；下单前仍需确认账户额度和最新状态。历史命中率不是盈利概率，不保证收益。</p></body></html>'
    )


def build_delivery_preview(analysis, report_id, created_at, *, now=None, budget_rechecked=False):
    """返回只读邮件预览及最终动作，不读取SMTP、文件或数据库。"""
    if not isinstance(analysis, dict) or not isinstance(analysis.get("actions", []), list):
        raise ValueError("报告格式异常")
    for field in ("execution_policy", "degradation", "completeness"):
        if analysis.get(field) is not None and not isinstance(analysis[field], dict):
            raise ValueError("报告门禁字段格式异常")
    actions = analysis.get("actions") or []
    if len(actions) > 100 or any(not isinstance(item, dict) for item in actions):
        raise ValueError("报告动作格式异常")
    clock = now or datetime.now(SHANGHAI)
    if clock.tzinfo is None:
        raise ValueError("预览时钟必须带时区")
    clock = clock.astimezone(SHANGHAI)
    reasons = _global_reasons(analysis, created_at, clock, budget_rechecked)
    policy = analysis.get("execution_policy") or {}
    try:
        cap = min(decimal_value(20), decimal_value(policy.get("daily_buy_remaining_rmb")), decimal_value(policy.get("monthly_buy_remaining_rmb")))
    except ValueError:
        cap = decimal_value(0)
        reasons.append("budget_not_rechecked")
    buy_count = sum(1 for item in actions if _positive_amount(item.get("action_amount")))
    final = [_delivery_action(item, reasons, clock, cap, buy_count > 1) for item in actions]
    return {
        "report_id": int(report_id), "preview_at": clock.isoformat(),
        "subject": f"FundAdvisor 每日报告 - {clock.date().isoformat()}",
        "html": _render_html(report_id, clock, final, reasons), "delivery_actions": final,
        "nonzero_action_count": sum(item["payment_rmb"] > 0 for item in final),
        "readonly": True, "email_sent": False, "report_generated": False,
        "holdings_updated": False, "auto_order": False,
        "requires_manual_order": True, "trading_calendar_owner": "原OpenClaw交易日门禁",
    }


def _positive_amount(value):
    """判断有限正向金额，异常值不扩大可执行候选集合。"""
    try:
        return decimal_value(value) > 0
    except ValueError:
        return False
