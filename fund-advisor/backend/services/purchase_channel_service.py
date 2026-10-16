"""只用可追溯的渠道快照计算申购付款预览，不联网、不下单、不修改数据。"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
CHANNEL_CONFIG_KEY = "purchase_channel_quotes_v1"
CENT = Decimal("0.01")
MAX_QUOTE_AGE = timedelta(minutes=30)


def decimal_value(value) -> Decimal:
    """严格读取非负有限金额，拒绝空值、布尔值和非有限数。"""
    if value is None or isinstance(value, bool):
        raise ValueError("数值缺失或类型非法")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("数值非法") from exc
    if not result.is_finite() or result < 0 or result > Decimal("1000000000000"):
        raise ValueError("数值超出范围")
    return result


def floor_money(value) -> Decimal:
    """付款金额向下取整到分，绝不因四舍五入突破预算或额度。"""
    return decimal_value(value).quantize(CENT, rounding=ROUND_DOWN)


def estimate_subscription(gross_payment, fee_rate_pct) -> dict:
    """按外扣比例法拆分总付款；固定费用及特殊收费方案不适用。"""
    gross = floor_money(gross_payment)
    rate = decimal_value(fee_rate_pct)
    if rate > 100:
        raise ValueError("百分比费率不得大于100")
    net = (gross / (1 + rate / 100)).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "gross_payment_rmb": float(gross),
        "subscription_fee_rate_pct": float(rate),
        "estimated_fee_rmb": float(gross - net),
        "estimated_net_investment_rmb": float(net),
        "amount_basis": "gross_payment_including_subscription_fee",
        "estimate_only": True,
        "settlement_basis": "以平台确认金额及份额为准，不用估算净值伪造实际份额",
    }


def quote_identity(quote: dict) -> tuple:
    """按代码、平台和支付方式区分渠道，同一代码不跨平台覆盖持仓。"""
    return tuple(str(quote.get(key) or "").strip() for key in ("fund_code", "platform", "payment_method"))


def inspect_quote(quote: dict, now: datetime) -> list[str]:
    """检查账户级快照的可买性与时效；公共页面不能代替账户可交易证明。"""
    reasons = []
    if quote.get("purchase_status") != "open":
        reasons.append("purchase_not_open")
    if quote.get("account_eligible") is not True or quote.get("evidence_scope") != "account_confirmed":
        reasons.append("account_not_confirmed")
    if not all(quote_identity(quote)) or not str(quote.get("source") or "").strip():
        reasons.append("quote_source_missing")
    if quote.get("fee_mode", "proportional") != "proportional":
        reasons.append("unsupported_fee_mode")
    try:
        rate = decimal_value(quote.get("subscription_fee_rate_pct"))
        if rate > 100:
            raise ValueError("费率越界")
        decimal_value(quote.get("min_purchase_rmb"))
        decimal_value(quote.get("daily_remaining_rmb"))
    except ValueError:
        reasons.append("fee_or_limit_unknown")
    try:
        observed = datetime.fromisoformat(str(quote.get("observed_at") or ""))
        if observed.tzinfo is None or now.tzinfo is None:
            raise ValueError("时间必须带时区")
        age = now - observed
        same_day = observed.astimezone(SHANGHAI).date() == now.astimezone(SHANGHAI).date()
        if not same_day or not timedelta(0) <= age <= MAX_QUOTE_AGE:
            reasons.append("quote_expired_or_future")
    except (ValueError, TypeError, OverflowError):
        reasons.append("quote_time_invalid")
    return reasons


def plan_purchase(fund_code: str, payment_cap, quotes, now: datetime | None = None) -> dict:
    """在同一基金代码的已确认渠道内选择申购费最低的付款预览。"""
    clock = now or datetime.now(SHANGHAI)
    result = {
        "status": "blocked", "gross_payment_rmb": 0.0,
        "estimated_fee_rmb": None, "estimated_net_investment_rmb": None,
        "requires_manual_order": True, "auto_order": False, "auto_reservation": False,
        "selection_basis": "subscription_fee_only", "total_cost_ranked": False,
        "redemption_fee_checked": False,
        "message": "仅比较申购费，不代表总成本最低；不自动换代码、下单或预约。",
        "channels": [],
    }
    try:
        cap = floor_money(payment_cap)
    except ValueError:
        result["reasons"] = ["payment_invalid"]
        return result
    if not isinstance(quotes, (list, tuple)):
        quotes = []
    matching = [item for item in quotes if isinstance(item, dict) and item.get("fund_code") == fund_code]
    identities = Counter(quote_identity(item) for item in matching)
    candidates = []
    for item in matching:
        reasons = inspect_quote(item, clock)
        if identities[quote_identity(item)] > 1:
            reasons.append("duplicate_channel_quote")
        view = {
            "fund_code": fund_code, "platform": item.get("platform"),
            "payment_method": item.get("payment_method"), "source": item.get("source"),
            "observed_at": item.get("observed_at"), "reasons": reasons,
            # 保存核验所需字段，邮件发送前可重新检查，而非永久信任 checked 标签。
            "purchase_status": item.get("purchase_status"),
            "account_eligible": item.get("account_eligible"),
            "evidence_scope": item.get("evidence_scope"),
            "fee_mode": item.get("fee_mode", "proportional"),
            "min_purchase_rmb": item.get("min_purchase_rmb"),
            "daily_remaining_rmb": item.get("daily_remaining_rmb"),
        }
        if not reasons:
            payment = min(cap, floor_money(item["daily_remaining_rmb"]))
            if payment <= 0 or payment < decimal_value(item["min_purchase_rmb"]):
                reasons.append("below_channel_minimum_or_no_quota")
            else:
                view.update(estimate_subscription(payment, item["subscription_fee_rate_pct"]))
                candidates.append(view)
        result["channels"].append(view)
    if not candidates:
        result["reasons"] = ["purchase_channel_unverified"]
        return result
    # 比较费率而非手续费绝对额，避免把只能买1元的渠道误判成更便宜。
    chosen = min(
        candidates,
        key=lambda item: (
            item["subscription_fee_rate_pct"], -item["gross_payment_rmb"],
            str(item["platform"]), str(item["payment_method"]),
        ),
    )
    result.update({key: value for key, value in chosen.items() if key != "reasons"})
    result.update(status="checked", reasons=[])
    return result


def load_channel_quotes(db) -> list[dict]:
    """只读已有配置表中的运营核验快照；没有快照时不伪造免费或开放。"""
    from backend.services.config_service import get_config

    raw = get_config(db, CHANNEL_CONFIG_KEY)
    if not raw:
        return []
    if len(raw) > 1000000:
        raise ValueError("渠道快照过大")
    data = json.loads(raw)
    if not isinstance(data, list) or len(data) > 100 or any(not isinstance(item, dict) for item in data):
        raise ValueError("渠道快照必须为最多100项的对象列表")
    return data
