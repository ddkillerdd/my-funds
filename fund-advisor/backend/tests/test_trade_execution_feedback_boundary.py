"""F07A：建议执行反馈边界的纯合成测试。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import trade_execution as trade_api
from backend.services import trade_execution_service as trade_service


class FakeQuery:
    """为服务层提供不连接数据库的最小查询替身。"""

    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, *conditions):
        """忽略 SQLAlchemy 条件并返回当前虚构查询。"""
        return self

    def order_by(self, *conditions):
        """忽略排序条件并返回当前虚构查询。"""
        return self

    def limit(self, amount):
        """忽略数量条件并返回当前虚构查询。"""
        return self

    def first(self):
        """返回虚构报告或既有反馈记录。"""
        if self.model is trade_service.AdvisorReport:
            return self.session.report
        if self.model is trade_service.TradeExecution:
            return self.session.existing
        return None

    def all(self):
        """返回虚构的反馈记录列表。"""
        return list(self.session.rows)


class FakeSession:
    """记录查询、写入、提交与回滚次数的虚构会话。"""

    def __init__(self, report=None, existing=None, commit_error=None):
        self.report = report
        self.existing = existing
        self.rows = []
        self.query_calls = 0
        self.add_calls = 0
        self.commit_calls = 0
        self.refresh_calls = 0
        self.rollback_calls = 0
        self.commit_error = commit_error

    def query(self, model):
        """创建虚构查询并记录数据库查询动作。"""
        self.query_calls += 1
        return FakeQuery(self, model)

    def add(self, row):
        """记录仅新增建议反馈记录。"""
        self.add_calls += 1
        self.rows.append(row)

    def commit(self):
        """记录提交并按夹具需要模拟提交失败。"""
        self.commit_calls += 1
        if self.commit_error:
            raise self.commit_error

    def refresh(self, row):
        """记录刷新动作并补齐虚构主键。"""
        self.refresh_calls += 1
        if getattr(row, "id", None) is None:
            row.id = 1

    def rollback(self):
        """记录回滚动作。"""
        self.rollback_calls += 1


def make_report(actions=None, holdings_health=None, report_id=7):
    """构造只含虚构建议 JSON 的报告对象。"""
    data = {
        "actions": actions or [],
        "holdings_health": holdings_health or [],
    }
    return SimpleNamespace(id=report_id, report_json=json.dumps(data, ensure_ascii=False))


def make_action(fund_code="A", **extra):
    """构造一条虚构的唯一基金建议。"""
    return {
        "fund_code": fund_code,
        "fund_name": f"基金{fund_code}",
        "action": "increase",
        "action_label": "加仓",
        "target_weight_pct": 20,
        "action_amount": 100,
        **extra,
    }


def call_record(session, **overrides):
    """使用固定合法字段调用建议反馈服务。"""
    values = {
        "db": session,
        "report_id": 7,
        "report_date": "2026-09-12",
        "fund_code": "A",
        "fund_name": "基金A",
        "actual_action": "same_as_suggest",
        "actual_amount": 20,
        "note": "合成测试",
    }
    values.update(overrides)
    return trade_service.record_manual(**values)


def assert_contract_response(payload):
    """断言响应携带精确的建议反馈安全合同。"""
    assert payload["record_scope"] == "advice_feedback_only"
    assert payload["holdings_updated"] is False
    assert payload["cash_updated"] is False
    assert payload["settlement_recorded"] is False
    assert payload["requires_trade_confirmation"] is True


def test_a_invalid_inputs_are_rejected_before_database_actions():
    """断言未知动作、负数/非有限金额和非法日期都在查询前拒绝。"""
    cases = [
        {"actual_action": "filled"},
        {"actual_amount": -100},
        {"actual_amount": float("inf")},
        {"report_date": "2026-9-2"},
        {"report_date": "2026-02-30"},
    ]
    for overrides in cases:
        session = FakeSession(report=make_report(actions=[make_action()]))
        with pytest.raises(ValueError):
            call_record(session, **overrides)
        assert session.query_calls == 0
        assert session.add_calls == 0
        assert session.commit_calls == 0


def test_b_missing_and_ambiguous_suggestions_never_write():
    """断言报告、基金和重复建议均不会静默写入。"""
    missing_report = FakeSession(report=None)
    with pytest.raises(ValueError, match="报告"):
        call_record(missing_report)
    assert missing_report.add_calls == 0
    assert missing_report.commit_calls == 0

    missing_fund = FakeSession(report=make_report(actions=[make_action("B")]))
    with pytest.raises(ValueError, match="不在报告建议"):
        call_record(missing_fund)
    assert missing_fund.add_calls == 0
    assert missing_fund.commit_calls == 0

    duplicate_actions = FakeSession(
        report=make_report(actions=[make_action(), make_action()])
    )
    with pytest.raises(ValueError, match="缺少平台/建议行标识"):
        call_record(duplicate_actions)
    assert duplicate_actions.add_calls == 0
    assert duplicate_actions.commit_calls == 0

    duplicate_health = FakeSession(
        report=make_report(
            actions=[],
            holdings_health=[make_action(), make_action()],
        )
    )
    with pytest.raises(ValueError, match="缺少平台/建议行标识"):
        call_record(duplicate_health)
    assert duplicate_health.add_calls == 0
    assert duplicate_health.commit_calls == 0


def test_c_valid_feedback_only_writes_trade_execution(monkeypatch):
    """断言合法反馈记录实际金额但不触碰持仓或现金。"""
    session = FakeSession(report=make_report(actions=[make_action()]))
    row = call_record(session)
    assert row.actual_action == "same_as_suggest"
    assert row.actual_amount == 20
    assert row.source == "manual"
    assert session.add_calls == 1
    assert session.commit_calls == 1
    assert session.rollback_calls == 0
    source = Path(trade_service.__file__).read_text(encoding="utf-8")
    assert "FundHolding" not in source
    assert "HoldingChange" not in source
    assert not hasattr(row, "holdings_updated")
    assert not hasattr(row, "cash_updated")
    monkeypatch.setattr(trade_service, "TradeExecution", trade_service.TradeExecution)


def test_d_api_contract_and_error_mapping(monkeypatch):
    """断言 POST、两个 GET 的安全字段及 400/500 异常映射。"""
    row = SimpleNamespace(
        to_dict=lambda: {
            "id": 1,
            "fund_code": "A",
            "actual_action": "same_as_suggest",
            "actual_amount": 20,
        }
    )
    monkeypatch.setattr(trade_api, "record_manual", lambda *args, **kwargs: row)
    body = trade_api.TradeExecIn(
        report_id=7,
        report_date="2026-09-12",
        fund_code="A",
        actual_action="same_as_suggest",
        actual_amount=20,
    )
    post_payload = trade_api.create_record(body, object())
    assert post_payload["ok"] is True
    assert_contract_response(post_payload)

    monkeypatch.setattr(
        trade_api,
        "list_by_report",
        lambda *args, **kwargs: [{"fund_code": "A"}],
    )
    report_payload = trade_api.get_by_report(7, object())
    assert report_payload["report_id"] == 7
    assert_contract_response(report_payload)

    monkeypatch.setattr(
        trade_api,
        "list_recent",
        lambda *args, **kwargs: [{"fund_code": "A"}],
    )
    recent_payload = trade_api.get_recent(50, object())
    assert_contract_response(recent_payload)

    monkeypatch.setattr(
        trade_api,
        "record_manual",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("建议反馈合同拒绝")),
    )
    with pytest.raises(HTTPException) as contract_error:
        trade_api.create_record(body, object())
    assert contract_error.value.status_code == 400
    assert contract_error.value.detail == "建议反馈合同拒绝"

    monkeypatch.setattr(
        trade_api,
        "record_manual",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("数据库故障")),
    )
    with pytest.raises(HTTPException) as server_error:
        trade_api.create_record(body, object())
    assert server_error.value.status_code == 500
    assert "数据库故障" in server_error.value.detail


def test_e_commit_failure_rolls_back_and_frontend_shows_boundary():
    """断言提交失败回滚且页面明确不更新真实持仓与现金。"""
    session = FakeSession(
        report=make_report(actions=[make_action()]),
        commit_error=RuntimeError("commit failed"),
    )
    with pytest.raises(RuntimeError, match="commit failed"):
        call_record(session)
    assert session.commit_calls == 1
    assert session.rollback_calls == 1

    frontend_path = (
        Path(__file__).parents[2]
        / "frontend"
        / "src"
        / "views"
        / "AdvisorView.vue"
    )
    source = frontend_path.read_text(encoding="utf-8")
    assert "实际操作（不自动更新持仓/现金）" in source
    for field in (
        "record_scope",
        "actual_amount_recorded",
        "holdings_updated",
        "cash_updated",
        "settlement_recorded",
        "requires_trade_confirmation",
    ):
        assert field in source
    assert "实际金额(元)" in source
    assert "已记录实际操作金额" in source


def test_f_actual_amount_direction_and_zero_rules():
    """断言前端填写正数金额后按实际动作保存方向，并严格处理未操作。"""
    reduce_session = FakeSession(report=make_report(actions=[make_action()]))
    reduced = call_record(
        reduce_session,
        actual_action="reduce",
        actual_amount=12.34,
    )
    assert reduced.actual_amount == -12.34

    none_session = FakeSession(report=make_report(actions=[make_action()]))
    none = call_record(none_session, actual_action="none", actual_amount=0)
    assert none.actual_amount == 0

    invalid_none = FakeSession(report=make_report(actions=[make_action()]))
    with pytest.raises(ValueError, match="未操作"):
        call_record(invalid_none, actual_action="none", actual_amount=1)
    assert invalid_none.commit_calls == 0
