"""模拟器初始权重、初始现金和买入持有基准的合成测试。"""

import math

import pytest

from engine.models import NavPoint
from engine.simulator import Simulator, simulate, simulate_portfolio


def _flat_funds(a_values=("1", "2"), b_values=("1", "1")):
    """创建两只日期一致的虚构基金净值。"""
    dates = ["2026-01-01", "2026-01-02"]
    return [
        {
            "code": "A",
            "name": "虚构基金A",
            "nav_history": [
                NavPoint(date=d, nav=float(value))
                for d, value in zip(dates, a_values)
            ],
        },
        {
            "code": "B",
            "name": "虚构基金B",
            "nav_history": [
                NavPoint(date=d, nav=float(value))
                for d, value in zip(dates, b_values)
            ],
        },
    ]


def _run_without_signals(funds, **kwargs):
    """用超长预热期避开调仓信号，只观察初始配置。"""
    return simulate_portfolio(
        funds,
        windows=[2],
        warmup=999,
        **kwargs,
    )[2]


def test_explicit_90_10_weights_change_real_shares_and_returns():
    """验证 90/10 权重真实形成 9000/1000 份额并获得 90% 收益。"""
    captured = {}

    def observe_initial_shares(shares, target_weights, nav_by_date, when, total_now):
        """记录首日份额并按目标权重保留现金。"""
        captured.setdefault("shares", dict(shares))
        return total_now * (1 - sum(target_weights.values()))

    result = _run_without_signals(
        _flat_funds(),
        initial_amount=10000,
        initial_weights={"A": 0.9, "B": 0.1},
        executor=observe_initial_shares,
    )

    assert captured["shares"]["A"] == pytest.approx(9000)
    assert captured["shares"]["B"] == pytest.approx(1000)
    assert result.daily[-1].total_value == pytest.approx(19000)
    assert result.buy_hold_return_pct == pytest.approx(90)
    assert result.strategy_return_pct == pytest.approx(90)


def test_none_initial_weights_keep_legacy_equal_weight_behavior():
    """验证不传 initial_weights 时仍按 50/50 初始化。"""
    result = _run_without_signals(
        _flat_funds(("1", "1"), ("1", "1")),
        initial_amount=10000,
    )

    assert result.daily[0].holdings_value == pytest.approx(10000)
    assert result.daily[0].target_weights == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}
    assert result.daily[-1].total_value == pytest.approx(10000)


def test_partial_initial_weights_keep_cash_in_both_curves():
    """验证 75% 初始权重留下的 2500 现金不从任一曲线消失。"""
    result = _run_without_signals(
        _flat_funds(("1", "1"), ("1", "1")),
        initial_amount=10000,
        initial_weights={"A": 0.5, "B": 0.25},
    )

    assert result.daily[0].cash == pytest.approx(2500)
    assert result.daily[-1].cash == pytest.approx(2500)
    assert result.daily[-1].holdings_value == pytest.approx(7500)
    assert result.daily[-1].total_value == pytest.approx(10000)
    assert result.buy_hold_return_pct == pytest.approx(0)
    assert result.strategy_return_pct == pytest.approx(0)


def test_explicit_weight_chain_reaches_class_and_convenience_api():
    """验证显式权重沿 Simulator 和 simulate 入口完整传递到报告。"""
    funds = _flat_funds(("1", "2"), ("1", "1"))
    weights = {"A": 0.9, "B": 0.1}
    class_report = Simulator(
        initial_amount=10000,
        initial_weights=weights,
        windows=[2],
        warmup=999,
    ).simulate(funds)
    convenience_report = simulate(
        funds,
        initial_amount=10000,
        initial_weights=weights,
        windows=[2],
        warmup=999,
    )

    assert class_report.initial_weights == weights
    assert convenience_report.initial_weights == weights
    assert class_report.windows[2].final_value == pytest.approx(19000)


def test_missing_first_nav_keeps_that_fund_allocation_as_cash():
    """验证窗口首日缺基金净值时，其显式分配金额继续留在现金。"""
    funds = [
        {
            "code": "A",
            "name": "虚构基金A",
            "nav_history": [
                NavPoint(date="2026-01-01", nav=1.0),
                NavPoint(date="2026-01-02", nav=2.0),
            ],
        },
        {
            "code": "B",
            "name": "虚构基金B",
            "nav_history": [NavPoint(date="2026-01-02", nav=1.0)],
        },
    ]
    result = _run_without_signals(
        funds,
        initial_amount=10000,
        initial_weights={"A": 0.9, "B": 0.1},
    )

    assert result.daily[0].cash == pytest.approx(1000)
    assert result.daily[-1].total_value == pytest.approx(19000)
    assert result.buy_hold_return_pct == pytest.approx(90)


@pytest.mark.parametrize(
    "weights",
    [
        {"A": 0.5},
        {"A": 0.5, "B": 0.5, "C": 0.0},
        {"A": -0.1, "B": 1.1},
        {"A": 1.1, "B": 0.0},
        {"A": math.nan, "B": 0.5},
        {"A": 0.7, "B": 0.4},
    ],
)
def test_invalid_explicit_weights_fail_closed(weights):
    """验证未知、遗漏、非法数值和超配权重均明确失败。"""
    with pytest.raises(ValueError):
        _run_without_signals(
            _flat_funds(("1", "1"), ("1", "1")),
            initial_amount=10000,
            initial_weights=weights,
        )


def test_zero_initial_weight_is_valid():
    """验证零权重合法且对应基金不被强制买入。"""
    result = _run_without_signals(
        _flat_funds(("1", "1"), ("1", "1")),
        initial_amount=10000,
        initial_weights={"A": 1.0, "B": 0.0},
    )

    assert result.daily[0].holdings_value == pytest.approx(10000)
    assert result.daily[0].target_weights["B"] == pytest.approx(0.0)
