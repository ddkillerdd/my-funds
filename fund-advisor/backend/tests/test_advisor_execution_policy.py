"""四只基金14:00行情映射与执行资金门禁的纯合成测试。"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.services import intraday
from backend.services.execution_policy import apply_execution_policy


SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_report(actions=None, *, degraded=False, quality="good"):
    """构造包含完整质量字段的虚构分析报告。"""
    actions = actions or [
        {
            "fund_code": "022430",
            "fund_name": "基金A",
            "action": "increase",
            "priority": "high",
            "action_amount": 18,
        }
    ]
    diagnosis = []
    for action in actions:
        diagnosis.append({
            "fund_code": action["fund_code"],
            "quant": {
                "data_quality": "good",
                "annual_return": 8.0,
            },
        })
    return {
        "actions": actions,
        "per_fund_diagnosis": diagnosis,
        "intraday_view": {},
        "degradation": {"any": degraded},
        "completeness": {"data_quality": quality},
    }


def test_current_four_funds_have_explicit_market_mapping():
    """断言当前四只基金全部有指数、行情代码和市场定义。"""
    current_four = {
        "018044": "纳斯达克100",
        "270042": "纳斯达克100",
        "022430": "中证A500",
        "013308": "恒生科技",
    }
    for fund_code, index_name in current_four.items():
        assert intraday.FUND_INTRADAY_INDEX[fund_code] == index_name
        assert intraday.INDEX_QTCODE[index_name]
        assert intraday.INDEX_MARKET[index_name] in {"CN", "HK", "US"}


def test_market_context_does_not_call_nasdaq_live_at_1400():
    """断言14:00仅A股和港股标为盘中，美股明确是最近交易时段。"""
    now = datetime(2026, 9, 21, 14, 0, tzinfo=SHANGHAI)
    assert intraday.market_quote_context("中证A500", now)["decision_live"] is True
    assert intraday.market_quote_context("恒生科技", now)["decision_live"] is True
    nasdaq = intraday.market_quote_context("纳斯达克100", now)
    assert nasdaq["decision_live"] is False
    assert "14:00不代表今晚纳指走势" in nasdaq["quote_semantics"]


def test_intraday_build_covers_four_without_network(monkeypatch):
    """断言四只基金均产生带来源和时效的行情视图。"""
    monkeypatch.setattr(
        intraday,
        "fetch_intraday",
        lambda index: {
            "price": 100.0,
            "pct_today": -1.2,
            "quote_time": "20260921140000",
        },
    )
    monkeypatch.setattr(
        intraday,
        "fetch_history",
        lambda index, days=5: [(f"2026-09-{day:02d}", 101.0) for day in range(14, 19)],
    )
    now = datetime(2026, 9, 21, 14, 0, tzinfo=SHANGHAI)
    current_codes = ["018044", "270042", "022430", "013308"]
    view = intraday.build_intraday_view(current_codes, now=now)
    assert set(view) == set(current_codes)
    assert all(item["source"] == "腾讯行情" for item in view.values())
    assert view["022430"]["decision_live"] is True
    assert view["018044"]["decision_live"] is False


def test_policy_allows_only_one_fund_and_caps_daily_amount():
    """断言同一天最多建议买一只，且总金额不超过20元。"""
    report = make_report([
        {"fund_code": "022430", "action": "increase", "priority": "medium", "action_amount": 15},
        {"fund_code": "013308", "action": "increase", "priority": "high", "action_amount": 50},
    ])
    result = apply_execution_policy(report, today=date(2026, 9, 21))
    by_code = {item["fund_code"]: item for item in result["actions"]}
    assert by_code["013308"]["action_amount"] == 20
    assert by_code["013308"]["policy_status"] == "capped"
    assert by_code["022430"]["action_amount"] == 0
    assert by_code["022430"]["policy_reasons"] == ["single_fund_daily_limit"]


def test_policy_counts_actual_amounts_for_daily_and_monthly_budget():
    """断言实际成交金额进入20元日限额和200元月限额。"""
    report = make_report()
    history = [
        {"report_date": "2026-09-21", "actual_amount": 8},
        {"report_date": "2026-09-10", "actual_amount": 182},
        {"report_date": "2026-09-09", "actual_amount": -50},
    ]
    result = apply_execution_policy(report, history, today=date(2026, 9, 21))
    assert result["actions"][0]["action_amount"] == 10
    assert result["execution_policy"]["daily_buy_remaining_rmb"] == 12
    assert result["execution_policy"]["monthly_buy_remaining_rmb"] == 10


def test_policy_blocks_consecutive_weekday_unless_strict_exception():
    """断言相邻交易日默认不买，严格实时超跌条件仅放宽冷却期。"""
    history = [{"report_date": "2026-09-18", "actual_amount": 10}]
    report = make_report()
    blocked = apply_execution_policy(report, history, today=date(2026, 9, 21))
    assert blocked["actions"][0]["action_amount"] == 0
    assert "consecutive_trading_day_cooldown" in blocked["actions"][0]["policy_reasons"]

    report["intraday_view"] = {
        "022430": {
            "decision_live": True,
            "realtime_ok": True,
            "signal": "oversold",
        }
    }
    allowed = apply_execution_policy(report, history, today=date(2026, 9, 21))
    assert allowed["actions"][0]["action_amount"] == 18
    assert allowed["actions"][0]["cooldown_exception"] is True


@pytest.mark.parametrize("degraded,quality", [(True, "good"), (False, "insufficient")])
def test_policy_fails_closed_when_report_data_is_not_ready(degraded, quality):
    """断言分析降级或数据不足时所有资金动作均归零。"""
    report = make_report(
        [{"fund_code": "022430", "action": "reduce", "priority": "high", "action_amount": -20}],
        degraded=degraded,
        quality=quality,
    )
    result = apply_execution_policy(report, today=date(2026, 9, 21))
    assert result["actions"][0]["raw_action_amount"] == -20
    assert result["actions"][0]["action_amount"] == 0
    assert result["actions"][0]["policy_status"] == "blocked"
