"""SimulatorService 初始金额、权重和显式组合边界的合成测试。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend.api.simulator as simulator_api
import backend.services.simulator_service as simulator_service_module
from backend.services.simulator_service import SimulatorService
from engine.models import (
    EXECUTION_ASSUMPTION,
    EXECUTION_DISCLAIMER,
    EXECUTION_SCOPE,
    NavPoint,
)
from backend.schemas.simulator import SimulationRequest


def _navs():
    """创建服务层使用的最小虚构净值历史。"""
    return [
        NavPoint(date="2026-01-01", nav=1.0),
        NavPoint(date="2026-01-02", nav=1.0),
    ]


def _patch_service(monkeypatch, nav_map):
    """替换数据库查询和引擎，捕获服务传入的初始权重。"""
    captured = {}

    class FakeSimulator:
        """只返回虚构报告，不启动真实模拟。"""

        def __init__(self, **kwargs):
            captured["simulator_kwargs"] = kwargs

        def simulate(self, funds):
            captured["funds"] = funds
            weights = captured["simulator_kwargs"].get("initial_weights")
            return SimpleNamespace(
                generated_at="2026-01-02T00:00:00",
                duration_seconds=0.0,
                initial_amount=captured["simulator_kwargs"]["initial_amount"],
                initial_weights=weights or {fund["code"]: 0.5 for fund in funds},
                target_vol=0.15,
                warmup=1,
                windows={},
                execution_scope=EXECUTION_SCOPE,
                execution_assumption=EXECUTION_ASSUMPTION,
                real_trade_ready=False,
                fees_included=False,
                settlement_delay_included=False,
                cash_locking_included=False,
                disclaimer=EXECUTION_DISCLAIMER,
            )

    monkeypatch.setattr(simulator_service_module, "Simulator", FakeSimulator)
    service = SimulatorService(None)
    monkeypatch.setattr(
        service,
        "_fund_info_map",
        lambda: {
            code: {"code": code, "name": code, "nav_days": len(navs)}
            for code, navs in nav_map.items()
        },
    )
    monkeypatch.setattr(service, "_get_nav_history", lambda code: nav_map.get(code, []))
    monkeypatch.setattr(service, "_build_summary", lambda report, windows: {})
    monkeypatch.setattr(
        service,
        "_build_advice",
        lambda report, windows, funds_used: [],
    )
    return service, captured


def test_service_passes_unrounded_explicit_weights_and_returns_engine_weights(monkeypatch):
    """验证服务把金额权重传给引擎，响应不再使用脱离引擎的展示权重。"""
    service, captured = _patch_service(monkeypatch, {"A": _navs(), "B": _navs()})
    result = service.run(
        funds_in=[
            {"fund_code": "A", "fund_name": "A", "amount": 9000},
            {"fund_code": "B", "fund_name": "B", "amount": 1000},
        ],
        initial_amount=10000,
        windows=[2],
        warmup=1,
    )

    expected = {"A": 0.9, "B": 0.1}
    assert captured["simulator_kwargs"]["initial_weights"] == expected
    assert result["initial_weights"] == expected
    assert captured["simulator_kwargs"]["initial_amount"] == 10000


def test_service_keeps_default_portfolio_without_explicit_weights(monkeypatch):
    """验证 funds 为空时保留默认组合和引擎等权兼容行为。"""
    service, captured = _patch_service(monkeypatch, {"A": _navs(), "B": _navs()})
    monkeypatch.setattr(
        service,
        "_default_portfolio",
        lambda info: (
            [
                {"code": "A", "name": "A", "nav_history": _navs()},
                {"code": "B", "name": "B", "nav_history": _navs()},
            ],
            [
                {"fund_code": "A", "fund_name": "A", "amount": 5000, "history_days": 2},
                {"fund_code": "B", "fund_name": "B", "amount": 5000, "history_days": 2},
            ],
            10000.0,
        ),
    )

    result = service.run(funds_in=[], windows=[2], warmup=1)

    assert captured["simulator_kwargs"]["initial_weights"] is None
    assert result["initial_weights"] == {"A": 0.5, "B": 0.5}


def test_service_rejects_duplicate_funds_and_underfunded_total(monkeypatch):
    """验证重复基金和总初始金额不足时明确拒绝。"""
    service, _ = _patch_service(monkeypatch, {"A": _navs(), "B": _navs()})
    with pytest.raises(ValueError, match="重复"):
        service.run(
            funds_in=[
                {"fund_code": "A", "amount": 5000},
                {"fund_code": "A", "amount": 5000},
            ],
            initial_amount=10000,
        )

    with pytest.raises(ValueError, match="不能小于"):
        service.run(
            funds_in=[
                {"fund_code": "A", "amount": 6000},
                {"fund_code": "B", "amount": 5000},
            ],
            initial_amount=10000,
        )


def test_service_rejects_any_explicit_fund_without_nav_history(monkeypatch):
    """验证显式组合缺任一基金净值时整次模拟失败。"""
    service, _ = _patch_service(monkeypatch, {"A": _navs(), "B": []})

    with pytest.raises(ValueError, match="B"):
        service.run(
            funds_in=[
                {"fund_code": "A", "amount": 9000},
                {"fund_code": "B", "amount": 1000},
            ],
            initial_amount=10000,
        )


def test_simulator_route_maps_value_error_to_http_400(monkeypatch):
    """验证模拟路由把用户参数错误映射为HTTP 400并保留detail。"""
    detail = "基金列表包含重复 fund_code: A"

    def raise_value_error(self, **kwargs):
        """模拟服务层返回明确的用户参数错误。"""
        raise ValueError(detail)

    monkeypatch.setattr(
        simulator_service_module.SimulatorService,
        "run",
        raise_value_error,
    )
    request = SimulationRequest(
        funds=[
            {"fund_code": "A", "amount": 5000},
            {"fund_code": "A", "amount": 5000},
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        simulator_api.simulator_run(request, db=None)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == detail
