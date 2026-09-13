"""F03A：纯引擎模拟执行边界的合成测试。"""

import pytest

from engine.models import NavPoint
from engine.simulator import Simulator


def _funds():
    """创建两只走势不同的虚构基金净值。"""
    dates = ["2026-01-01", "2026-01-02"]
    return [
        {
            "code": "A",
            "name": "虚构上涨基金",
            "nav_history": [
                NavPoint(date=day, nav=nav)
                for day, nav in zip(dates, [1.0, 2.0])
            ],
        },
        {
            "code": "B",
            "name": "虚构下跌基金",
            "nav_history": [
                NavPoint(date=day, nav=nav)
                for day, nav in zip(dates, [1.0, 1.0])
            ],
        },
    ]


def test_engine_report_exposes_exact_execution_scope_and_disclaimer():
    """断言引擎报告的机器边界和免责声明完整且精确。"""
    report = Simulator(
        initial_amount=10000,
        windows=[2],
        warmup=999,
    ).simulate(_funds())

    assert report.execution_scope == "idealized_signal_replay_only"
    assert report.execution_assumption == "same_day_nav_instant_rebalance"
    assert report.real_trade_ready is False
    assert report.fees_included is False
    assert report.settlement_delay_included is False
    assert report.cash_locking_included is False
    for phrase in (
        "当天净值同时用于信号和即时再平衡",
        "申赎费",
        "确认延迟",
        "资金占用",
        "不可作为可实现收益",
    ):
        assert phrase in report.disclaimer


def test_engine_boundary_fields_do_not_replace_existing_numeric_result():
    """断言边界字段附加在原结果上而不改变基础回放数值。"""
    report = Simulator(
        initial_amount=10000,
        windows=[2],
        warmup=999,
        initial_weights={"A": 0.9, "B": 0.1},
    ).simulate(_funds())

    assert report.initial_amount == pytest.approx(10000)
    assert report.initial_weights == {"A": 0.9, "B": 0.1}
    assert report.windows[2].final_value == pytest.approx(19000)
