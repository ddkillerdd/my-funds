"""渠道可买性与含费预算的纯合成回归测试，不访问数据库或网络。"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from backend.services.execution_policy import apply_execution_policy
from backend.services import config_service, execution_policy
from backend.services.purchase_channel_service import estimate_subscription, load_channel_quotes, plan_purchase


DAY = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 14, 0, tzinfo=timezone(timedelta(hours=8)))


def report(amount=20):
    """构造没有真实持仓的量化候选。"""
    return {
        "actions": [{"fund_code": "000001", "action": "increase", "action_amount": amount}],
        "degradation": {"any": False},
        "completeness": {"data_quality": "good"},
    }


def quote(**changes):
    """构造当天由用户确认可交易的虚构渠道报价。"""
    return {
        "fund_code": "000001", "platform": "合成平台甲", "payment_method": "合成支付",
        "purchase_status": "open", "account_eligible": True,
        "subscription_fee_rate_pct": "0.15", "min_purchase_rmb": "1",
        "daily_remaining_rmb": "100", "observed_at": "2026-10-15T13:55:00+08:00",
        "source": "合成测试报价", "evidence_scope": "account_confirmed", **changes,
    }


def apply(data=None, quotes=None, executions=()):
    """以固定时钟执行生产门禁，隔离日期与外部依赖。"""
    return apply_execution_policy(
        data or report(), executions, today=DAY, now=NOW, channel_quotes=quotes,
    )


def test_unknown_channel_never_becomes_executable_buy():
    """缺少渠道证据时保留候选但最终付款必须为零。"""
    action = apply_execution_policy(report(), today=DAY)["actions"][0]
    assert action["raw_action_amount"] == 20
    assert action["action_amount"] == 0
    assert action["purchase_check"]["status"] == "blocked"


def test_fee_is_inside_twenty_and_rounds_to_fen():
    """20元是总付款，净投入19.97加申购费0.03恰好20元。"""
    original = report()
    before = deepcopy(original)
    action = apply(original, [quote()])["actions"][0]
    assert action["action_amount"] == 20
    check = action["purchase_check"]
    assert check["gross_payment_rmb"] == 20
    assert check["estimated_fee_rmb"] == 0.03
    assert check["estimated_net_investment_rmb"] == 19.97
    assert original == before


@pytest.mark.parametrize("changes", [
    {"purchase_status": "paused"}, {"purchase_status": "unknown"},
    {"account_eligible": None}, {"evidence_scope": "public_only"},
    {"subscription_fee_rate_pct": None}, {"daily_remaining_rmb": None},
    {"observed_at": "2026-10-14T13:55:00+08:00"},
    {"observed_at": "2026-10-15T14:01:00+08:00"},
    {"observed_at": "2026-10-15T13:55:00"},
    {"fund_code": "000002"}, {"subscription_fee_rate_pct": "NaN"},
])
def test_invalid_or_unconfirmed_quote_fails_closed(changes):
    """暂停、过期、未来、无时区和缺失账户证据一律不能买。"""
    assert apply(quotes=[quote(**changes)])["actions"][0]["action_amount"] == 0


def test_channel_limit_and_minimum_are_both_enforced():
    """渠道仅剩8元但起购10元时，不凑额、不换基金。"""
    assert apply(quotes=[quote(daily_remaining_rmb="8", min_purchase_rmb="10")])["actions"][0]["action_amount"] == 0
    action = apply(quotes=[quote(daily_remaining_rmb="8")])["actions"][0]
    assert action["action_amount"] == 8
    assert action["purchase_check"]["estimated_fee_rmb"] == 0.01


def test_all_platform_spending_shares_one_budget_and_no_sell_replenishment():
    """平台甲乙付款合计占预算，卖出不补回本月买入额度。"""
    history = [
        {"report_date": "2026-10-15", "actual_amount": 5, "platform": "甲"},
        {"report_date": "2026-10-15", "actual_amount": 7, "platform": "乙"},
        {"report_date": "2026-10-10", "actual_amount": 185},
        {"report_date": "2026-10-10", "actual_amount": -80},
    ]
    result = apply(quotes=[quote(subscription_fee_rate_pct="0")], executions=history)
    assert result["actions"][0]["action_amount"] == 3
    assert result["execution_policy"]["monthly_buy_remaining_rmb"] == 3


def test_cheaper_confirmed_same_fund_channel_without_substitution():
    """只在相同代码已核验渠道内比较申购费，不换成另一只基金。"""
    candidates = [quote(), quote(platform="合成平台乙", subscription_fee_rate_pct="0"),
                  quote(fund_code="000002", subscription_fee_rate_pct="0")]
    check = apply(quotes=candidates)["actions"][0]["purchase_check"]
    assert check["platform"] == "合成平台乙"
    assert check["estimated_fee_rmb"] == 0
    assert check["selection_basis"] == "subscription_fee_only"


def test_blocked_top_candidate_does_not_redirect_money_to_second_fund():
    """最高优先级基金不可买时保留现金，不自动挪给其他基金。"""
    data = report()
    data["actions"][0]["priority"] = "high"
    data["actions"].append({"fund_code": "000002", "action": "increase", "action_amount": 20, "priority": "low"})
    result = apply(data, [quote(purchase_status="paused"), quote(fund_code="000002")])
    assert all(item["action_amount"] == 0 for item in result["actions"])


def test_channel_proof_cannot_bypass_analysis_or_cooldown():
    """零费率也不能绕过数据质量和冷却期门禁。"""
    data = report()
    data["degradation"]["any"] = True
    assert apply(data, [quote()])["actions"][0]["action_amount"] == 0
    history = [{"report_date": "2026-10-14", "actual_amount": 10}]
    assert apply(quotes=[quote()], executions=history)["actions"][0]["action_amount"] == 0


def test_decimal_boundary_and_zero_fee():
    """总付款向下到分，未知费率不默认为免费。"""
    assert estimate_subscription("19.999", "0")["gross_payment_rmb"] == 19.99
    with pytest.raises(ValueError):
        estimate_subscription(20, None)
    assert estimate_subscription(20, "0.06")["estimated_fee_rmb"] == 0.01
    assert estimate_subscription(20, "0.12")["estimated_fee_rmb"] == 0.02


def test_conflicting_duplicate_quotes_and_fixed_fees_are_not_selected():
    """同渠道重复证据和不支持的固定费用不能被静默挑选。"""
    assert apply(quotes=[quote(), quote(subscription_fee_rate_pct="0")])["actions"][0]["action_amount"] == 0
    assert apply(quotes=[quote(fee_mode="fixed")])["actions"][0]["action_amount"] == 0


def test_quote_older_than_thirty_minutes_fails_and_cross_timezone_is_consistent():
    """同日陈旧快照仍失效，等价UTC时间正常通过。"""
    assert apply(quotes=[quote(observed_at="2026-10-15T13:29:59+08:00")])["actions"][0]["action_amount"] == 0
    assert apply(quotes=[quote(observed_at="2026-10-15T05:55:00Z")])["actions"][0]["action_amount"] == 20


def test_old_checked_snapshot_is_removed_when_policy_fails():
    """再次计算遇降级时必须清掉旧的通过状态。"""
    old = apply(quotes=[quote()])
    old["degradation"]["any"] = True
    result = apply(old, [quote()])
    assert result["actions"][0]["action_amount"] == 0
    assert "purchase_check" not in result["actions"][0]
    closed = execution_policy.fail_closed_execution_policy(old)
    assert "purchase_check" not in closed["actions"][0]


def test_positive_non_buy_action_is_blocked():
    """矛盾动作不能跳过正向付款门禁。"""
    data = report()
    data["actions"][0]["action"] = "hold"
    assert apply(data, [quote()])["actions"][0]["action_amount"] == 0


def test_config_reader_only_reads_one_key_and_rejects_bad_json(monkeypatch):
    """配置读取不写数据库，缺失或坏格式不会补成零费率报价。"""
    calls = []

    def read_config(db, key):
        """记录唯一只读键并返回虚构报价。"""
        calls.append(key)
        return json.dumps([quote()])

    monkeypatch.setattr(config_service, "get_config", read_config)
    assert len(load_channel_quotes(object())) == 1
    assert calls == ["purchase_channel_quotes_v1"]
    monkeypatch.setattr(config_service, "get_config", lambda *args: None)
    assert load_channel_quotes(object()) == []
    monkeypatch.setattr(config_service, "get_config", lambda *args: '{"bad":true}')
    with pytest.raises(ValueError):
        load_channel_quotes(object())


def test_database_entry_reaches_channel_gate_without_any_writes(monkeypatch):
    """直接覆盖日报调用的数据库入口，用只支持查询的会话证明无写入。"""
    class ReadOnlySession:
        """缺少任何写方法的虚构会话。"""

        def query(self, model):
            """返回空的虚构成交反馈查询。"""
            return self

        def filter(self, *conditions):
            """保持虚构查询链。"""
            return self

        def all(self):
            """没有买入支出。"""
            return []

        def execute(self, statement):
            """读取已有配置键，不提供写入接口。"""
            assert statement.compile().params == {"key_1": "purchase_channel_quotes_v1"}
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(value=json.dumps([quote()])))

    result = execution_policy.apply_execution_policy_from_db(ReadOnlySession(), report(), today=DAY, now=NOW)
    assert result["actions"][0]["purchase_check"]["estimated_fee_rmb"] == 0.03
