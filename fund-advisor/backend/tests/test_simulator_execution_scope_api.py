"""F03A：服务、schema、API 与页面边界的纯合成测试。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import backend.api.simulator as simulator_api
import backend.services.simulator_service as simulator_service_module
from backend.schemas.simulator import SimulationRequest, SimulationResponse
from backend.services.simulator_service import SimulatorService
from engine.models import NavPoint


def _contract():
    """返回固定的六字段机器合同。"""
    return {
        "execution_scope": "idealized_signal_replay_only",
        "execution_assumption": "same_day_nav_instant_rebalance",
        "real_trade_ready": False,
        "fees_included": False,
        "settlement_delay_included": False,
        "cash_locking_included": False,
    }


def _disclaimer():
    """返回完整的虚构响应免责声明。"""
    return (
        "当天净值同时用于信号和即时再平衡；未计申赎费、确认延迟、资金占用、"
        "净值发布时间、申赎截止和跨市场规则；结果只用于信号方向研究，"
        "不可作为可实现收益或交易建议。"
    )


def _fake_window():
    """构造一条足够服务层汇总使用的虚构正收益窗口。"""
    return SimpleNamespace(
        window_days=365,
        start_date="2026-01-01",
        end_date="2026-12-31",
        initial_amount=100.0,
        final_value=101.0,
        strategy_return_pct=1.0,
        buy_hold_return_pct=0.0,
        excess_return_pct=1.0,
        strategy_max_drawdown_pct=1.0,
        buy_hold_max_drawdown_pct=1.0,
        final_weights={},
        daily=[],
        per_fund={},
    )


def _fake_report(**overrides):
    """构造带有可覆盖执行边界的虚构引擎报告。"""
    values = {
        "generated_at": "2026-09-12T00:00:00",
        "duration_seconds": 0.0,
        "initial_amount": 100.0,
        "initial_weights": {"A": 1.0},
        "target_vol": 0.15,
        "warmup": 1,
        "windows": {365: _fake_window()},
        "execution_scope": _contract()["execution_scope"],
        "execution_assumption": _contract()["execution_assumption"],
        "real_trade_ready": False,
        "fees_included": False,
        "settlement_delay_included": False,
        "cash_locking_included": False,
        "disclaimer": _disclaimer(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_service(monkeypatch, report):
    """替换引擎和基金数据源，形成不连接数据库的服务。"""
    class FakeSimulator:
        """只返回虚构引擎报告。"""

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def simulate(self, funds):
            return report

    monkeypatch.setattr(simulator_service_module, "Simulator", FakeSimulator)
    service = SimulatorService(None)
    monkeypatch.setattr(
        service,
        "_fund_info_map",
        lambda: {"A": {"code": "A", "name": "虚构基金A", "nav_days": 2}},
    )
    monkeypatch.setattr(
        service,
        "_get_nav_history",
        lambda code: [
            NavPoint(date="2026-01-01", nav=1.0),
            NavPoint(date="2026-01-02", nav=1.0),
        ],
    )
    return service


def _run_service(service):
    """运行一次固定的虚构单基金服务请求。"""
    return service.run(
        funds_in=[{"fund_code": "A", "fund_name": "虚构基金A", "amount": 100}],
        initial_amount=100,
        windows=[365],
        warmup=1,
    )


def test_service_rejects_missing_or_mismatched_engine_contract(monkeypatch):
    """断言服务在摘要和建议生成前拒绝缺失或错误边界。"""
    invalid_reports = []
    empty_missing = _fake_report(windows={})
    for field in (
        "execution_scope",
        "execution_assumption",
        "real_trade_ready",
        "fees_included",
        "settlement_delay_included",
        "cash_locking_included",
        "disclaimer",
    ):
        delattr(empty_missing, field)
    invalid_reports.append(empty_missing)
    missing = _fake_report()
    del missing.execution_scope
    invalid_reports.append(missing)
    invalid_reports.extend(
        [
            _fake_report(execution_scope="live"),
            _fake_report(execution_assumption="next_day_nav"),
            _fake_report(real_trade_ready=True),
            _fake_report(fees_included=True),
            _fake_report(settlement_delay_included=True),
            _fake_report(cash_locking_included=True),
            _fake_report(disclaimer=None),
            _fake_report(disclaimer=""),
            _fake_report(disclaimer="   "),
            _fake_report(disclaimer="边界说明不完整"),
        ]
    )

    for report in invalid_reports:
        service = _patch_service(monkeypatch, report)
        if report is empty_missing:
            with pytest.raises(ValueError, match="execution_scope"):
                _run_service(service)
            assert not hasattr(report, "execution_scope")
            assert not hasattr(report, "disclaimer")
            continue
        monkeypatch.setattr(
            service,
            "_build_summary",
            lambda *args: pytest.fail("边界错误时不得构造摘要"),
        )
        monkeypatch.setattr(
            service,
            "_build_advice",
            lambda *args: pytest.fail("边界错误时不得构造建议"),
        )
        with pytest.raises(ValueError, match="执行边界"):
            _run_service(service)


def test_service_returns_contract_disclaimer_and_research_only_advice(monkeypatch):
    """断言服务显式返回六字段，正结果和动作均保持研究边界。"""
    result = _run_service(_patch_service(monkeypatch, _fake_report()))

    for key, value in _contract().items():
        assert result[key] == value
    assert result["disclaimer"] == _disclaimer()
    assert "理想化" in result["summary"]["verdict"]
    assert "不能推断可实现盈利" in result["summary"]["verdict"]
    for advice in result["advice"]:
        if advice["action"]:
            assert advice["action"].startswith("仅用于下一轮理想化模拟验证：")


def _response_payload():
    """创建 API 返回所需的完整虚构响应。"""
    return {
        **_contract(),
        "generated_at": "2026-09-12T00:00:00",
        "duration_seconds": 0.0,
        "initial_amount": 100.0,
        "initial_weights": {"A": 1.0},
        "target_vol": 0.15,
        "warmup": 1,
        "windows": {},
        "summary": {
            "avg_excess_pct": 0.0,
            "best_excess_pct": 0.0,
            "worst_excess_pct": 0.0,
            "profitable_windows": 0,
            "total_windows": 0,
            "overall_profitable": False,
            "profit_confidence": "low",
            "verdict": "理想化回放无足够数据，不能推断可实现盈利",
        },
        "advice": [],
        "funds_used": [],
        "disclaimer": _disclaimer(),
    }


def test_api_and_schema_preserve_contract_and_map_boundary_error(monkeypatch):
    """断言 API schema 保留机器合同，ValueError 返回 400 并保留 detail。"""
    class FakeService:
        """返回完整虚构结果的服务替身。"""

        def __init__(self, db):
            self.db = db

        def run(self, **kwargs):
            return _response_payload()

    monkeypatch.setattr(simulator_service_module, "SimulatorService", FakeService)
    request = SimulationRequest(
        funds=[{"fund_code": "A", "amount": 100}],
        windows=[30],
        warmup=1,
    )
    response = simulator_api.simulator_run(request, db=object())
    payload = response.model_dump()
    for key, value in _contract().items():
        assert payload[key] == value
    assert payload["disclaimer"] == _disclaimer()
    with pytest.raises(ValidationError):
        SimulationResponse(
            **{
                key: value
                for key, value in _response_payload().items()
                if key != "execution_scope"
            }
        )

    detail = "模拟执行边界缺失或无效"

    class ErrorService:
        """返回明确边界错误的服务替身。"""

        def __init__(self, db):
            self.db = db

        def run(self, **kwargs):
            raise ValueError(detail)

    monkeypatch.setattr(simulator_service_module, "SimulatorService", ErrorService)
    with pytest.raises(HTTPException) as exc_info:
        simulator_api.simulator_run(request, db=object())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == detail


def test_frontend_checks_boundary_before_rendering_and_uses_safe_labels():
    """断言页面赋值前校验六字段并展示醒目的理想化限制。"""
    path = (
        Path(__file__).parents[2]
        / "frontend"
        / "src"
        / "views"
        / "SimulatorView.vue"
    )
    source = path.read_text(encoding="utf-8")
    for phrase in (
        "同日净值即时再平衡",
        "未计费用/确认延迟/资金占用",
        "不可视为可实现收益",
        "策略信号理想化回放",
        "理想化回放结果摘要",
        "参数研究观察（不可直接执行）",
        "模拟执行边界缺失或无效",
    ):
        assert phrase in source
    for field in _contract():
        assert field in source
    assert "策略回测 · 盈利能力分析" not in source
    assert "盈利判定总结" not in source
    assert "优化建议（以盈利为目标）" not in source
    guard_index = source.index("hasValidExecutionContract(data)")
    assign_index = source.index("result.value = data")
    assert guard_index < assign_index
