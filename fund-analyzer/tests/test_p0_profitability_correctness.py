"""盈利链路 P0 正确性回归测试。

这些测试只使用合成净值和虚构金额，不连接服务器数据库，也不读取真实持仓。
"""

from datetime import date, timedelta

import pytest

from engine.allocation import allocate_incremental_capital
from engine.analyzer import Analyzer
from engine.backtest import summarize, validate_advice
from engine.models import DebateSummary, FundDiagnosis, NavPoint, QuantIndicators, AnalysisReport, PortfolioInput
from engine.quant import compute_all
from engine.simulator import simulate_portfolio


# 生成稳定的合成净值序列，避免测试依赖外部行情。
def _flat_nav(count: int = 90, start: str = "2025-01-01") -> list[NavPoint]:
    first = date.fromisoformat(start)
    return [
        NavPoint(date=(first + timedelta(days=i)).isoformat(), nav=1.0 + i * 0.001)
        for i in range(count)
    ]


# 返回固定目标仓位策略，用于验证模拟器不会偷偷归一化权重。
def _fixed_target(target: float):
    def strategy(qi, regime, current_weight, total_mv, **kwargs):
        return {"action": "hold", "target_weight": target}

    return strategy


# 验证单基金 25% 目标会保留 75% 现金，而不是被归一化为满仓。
def test_simulator_preserves_cash_for_partial_target_weight():
    funds = [{"code": "F", "name": "合成基金", "nav_history": _flat_nav()}]
    result = simulate_portfolio(
        funds,
        initial_amount=100.0,
        windows=[30],
        warmup=20,
        strategy=_fixed_target(0.25),
    )[30]

    active = [snap for snap in result.daily if snap.target_weights["F"] == pytest.approx(0.25)]
    assert active, "预热完成后应出现固定目标仓位"
    total_value = active[-1].total_value
    assert active[-1].cash / total_value == pytest.approx(0.75, abs=0.001)
    assert active[-1].holdings_value / total_value == pytest.approx(0.25, abs=0.001)


# 验证预热期没有信号时维持现有仓位，不把缺失动作误判为清仓。
def test_simulator_keeps_current_weight_before_signal_warmup():
    funds = [{"code": "F", "name": "合成基金", "nav_history": _flat_nav()}]
    result = simulate_portfolio(
        funds,
        initial_amount=100.0,
        windows=[30],
        warmup=80,
        strategy=_fixed_target(0.25),
    )[30]

    first = result.daily[0]
    assert first.target_weights["F"] == pytest.approx(1.0)
    assert first.cash == pytest.approx(0.0, abs=0.01)


# 验证明确的零仓位目标会全部转为现金。
def test_simulator_zero_target_is_all_cash():
    funds = [{"code": "F", "name": "合成基金", "nav_history": _flat_nav()}]
    result = simulate_portfolio(
        funds,
        initial_amount=100.0,
        windows=[30],
        warmup=20,
        strategy=_fixed_target(0.0),
    )[30]

    assert result.daily[-1].target_weights["F"] == pytest.approx(0.0)
    assert result.daily[-1].cash == pytest.approx(100.0, abs=0.01)
    assert result.daily[-1].holdings_value == pytest.approx(0.0, abs=0.01)


# 验证零目标配置不会退化为等权满仓。
def test_allocation_zero_target_does_not_reinvest():
    result = allocate_incremental_capital(
        current_mv={"F": 1.48},
        target_weight={"F": 0.0},
        available_capital=10.0,
    )

    item = result["per_fund"]["F"]
    assert item["target_amount"] == pytest.approx(0.0)
    assert item["action_amount"] == pytest.approx(-1.48)
    assert result["allocated_capital"] == pytest.approx(0.0)
    assert any("现金" in note or "清仓" in note for note in result["notes"])


# 验证轮换时可以使用已确认卖出释放的资金，而不是错误地阻止买入。
def test_allocation_rotation_uses_released_cash():
    result = allocate_incremental_capital(
        current_mv={"A": 10.0, "B": 0.0},
        target_weight={"A": 0.0, "B": 1.0},
        available_capital=0.0,
    )

    assert result["per_fund"]["A"]["target_amount"] == pytest.approx(0.0)
    assert result["per_fund"]["B"]["target_amount"] == pytest.approx(10.0)
    assert result["per_fund"]["B"]["action_amount"] == pytest.approx(10.0)


# 验证超配权重直接暴露上游错误，不在分配器内静默改写策略目标。
def test_allocation_rejects_weight_sum_over_one():
    with pytest.raises(ValueError, match="超过100%"):
        allocate_incremental_capital(
            current_mv={"A": 10.0, "B": 10.0},
            target_weight={"A": 0.7, "B": 0.7},
            available_capital=0.0,
        )


# 验证缺失目标时保留现有绝对金额，显式零目标仍由上一测试覆盖为清仓。
def test_allocation_missing_target_preserves_current_amount():
    result = allocate_incremental_capital(
        current_mv={"F": 10.0},
        target_weight={},
        available_capital=5.0,
        current_weight={"F": 10.0 / 15.0},
    )

    item = result["per_fund"]["F"]
    assert item["target_amount"] == pytest.approx(10.0)
    assert item["action_amount"] == pytest.approx(0.0)


# 验证分析器不会把缺失 target_weight 的旧动作写成清仓目标。
def test_analyzer_preserves_fund_without_explicit_target_weight():
    qi = QuantIndicators(
        fund_code="F",
        fund_name="合成基金",
        fund_type="指数型",
        current_mv=10.0,
        cost=10.0,
        mv_ratio=1.0,
        pnl_amount=0.0,
        pnl_pct=0.0,
        is_money_fund=False,
        nav_history_days=30,
    )
    fd = FundDiagnosis(
        fund_code="F",
        fund_name="合成基金",
        ground_truth=qi,
        debate_summary=DebateSummary(action={"action": "hold"}),
    )
    report = AnalysisReport(per_fund_diagnosis=[fd])

    Analyzer.__new__(Analyzer)._apply_incremental_allocation(
        report,
        [qi],
        PortfolioInput(holdings=[], available_capital=5.0),
    )

    assert fd.debate_summary.action["target_amount"] == pytest.approx(10.0)
    assert fd.debate_summary.action["action_amount"] == pytest.approx(0.0)


# 验证模拟器也拒绝跨基金超配，而不是把策略权重悄悄归一化。
def test_simulator_rejects_weight_sum_over_one():
    funds = [
        {"code": "A", "name": "合成基金A", "nav_history": _flat_nav()},
        {"code": "B", "name": "合成基金B", "nav_history": _flat_nav()},
    ]

    with pytest.raises(ValueError, match="超过100%"):
        simulate_portfolio(
            funds,
            initial_amount=100.0,
            windows=[30],
            warmup=20,
            strategy=_fixed_target(0.7),
        )


# 验证量化结果保留输入历史的最新净值，供后端记录建议时点。
def test_quant_indicators_keep_latest_nav_and_date():
    history = _flat_nav(count=3)
    holding = {
        "fund_code": "F",
        "fund_name": "合成基金",
        "fund_type": "指数型",
        "current_mv": 10.0,
        "cost": 10.0,
        "mv_ratio": 1.0,
        "is_money_fund": False,
        "nav_history": history,
    }
    from engine.models import FundHolding

    qi = compute_all(FundHolding(**holding))
    assert qi.current_nav == pytest.approx(history[-1].nav)
    assert qi.current_nav_date == history[-1].date


# 验证买入类动作全部参与正向命中判断。
@pytest.mark.parametrize("action", ["buy", "increase", "add"])
def test_backtest_maps_buy_actions_to_positive_direction(action):
    verdict = validate_advice(
        action,
        nav_before=1,
        nav_after=1.10,
        benchmark_before=1,
        benchmark_after=1.00,
    )
    assert verdict.verdict == "hit"


# 验证卖出类动作全部参与负向命中判断。
@pytest.mark.parametrize("action", ["sell", "reduce", "decrease"])
def test_backtest_maps_sell_actions_to_negative_direction(action):
    verdict = validate_advice(
        action,
        nav_before=1,
        nav_after=0.90,
        benchmark_before=1,
        benchmark_after=1.00,
    )
    assert verdict.verdict == "hit"


# 验证中性动作不进入方向命中率分母。
def test_backtest_summary_excludes_only_neutral_actions_from_direction_rate():
    verdicts = [
        validate_advice("buy", 1, 1.10, 1, 1),
        validate_advice("sell", 1, 0.90, 1, 1),
        validate_advice("hold", 1, 1.10, 1, 1),
        validate_advice("watch", 1, 0.90, 1, 1),
    ]
    result = summarize(verdicts)
    assert result["total"] == 4
    assert result["directional"] == 2
    assert result["hits"] == 2
    assert result["neutral"] == 2
    assert result["hit_rate"] == pytest.approx(1.0)
