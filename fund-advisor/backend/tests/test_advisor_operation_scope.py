"""F11A：run-advisor 操作边界与伪只读拒绝的纯合成测试。"""

from pathlib import Path

import pytest
from fastapi import HTTPException

import backend.api.scheduler as scheduler_api
import backend.scheduler.advisor_job as advisor_job_module
from backend.scheduler.advisor_job import AdvisorJob


class _FakeDB:
    """记录数据库副作用的虚构 Session。"""

    def __init__(self):
        self.add_count = 0
        self.query_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def add(self, obj):
        """记录新增对象调用。"""
        self.add_count += 1

    def query(self, *args, **kwargs):
        """记录查询调用并返回自身作为虚构查询对象。"""
        self.query_count += 1
        return self

    def commit(self):
        """记录提交调用。"""
        self.commit_count += 1

    def rollback(self):
        """记录回滚调用。"""
        self.rollback_count += 1

    def refresh(self, obj):
        """提供持久化测试桩所需的刷新接口。"""


class _FakeAdvisorService:
    """返回最小虚构成功报告并记录分析调用。"""

    calls = 0

    def __init__(self, db):
        self.db = db

    def analyze(self, model=None):
        """返回不降级的虚构分析结果。"""
        type(self).calls += 1
        return {
            "model": model or "test-model",
            "portfolio_diagnosis": {"overall_assessment": "合成分析完成"},
            "holdings_health": [],
            "actions": [],
        }


class _FakeBacktestService:
    """记录回测验证、命中率更新和反馈调用。"""

    calls = {"validate_due": 0, "refresh_hit_rates": 0, "get_feedback": 0}

    def __init__(self, db):
        self.db = db

    def validate_due(self):
        """记录待验证样本检查。"""
        type(self).calls["validate_due"] += 1
        return 0

    def refresh_hit_rates(self, rolling_window=10):
        """记录命中率刷新。"""
        type(self).calls["refresh_hit_rates"] += 1
        return 0

    def get_feedback(self):
        """记录反馈读取并返回最小虚构反馈。"""
        type(self).calls["get_feedback"] += 1
        return type("Feedback", (), {"has_evidence": False, "prompt_hint": ""})()


class _FailingSMTP:
    """一旦构造就失败的本地 SMTP 保护桩。"""

    calls = 0

    def __init__(self, *args, **kwargs):
        type(self).calls += 1
        raise AssertionError("本地 SMTP 不应被调用")


def _patch_services(monkeypatch):
    """隔离分析、回测和本地 SMTP 依赖。"""
    _FakeAdvisorService.calls = 0
    _FakeBacktestService.calls = {
        "validate_due": 0,
        "refresh_hit_rates": 0,
        "get_feedback": 0,
    }
    _FailingSMTP.calls = 0
    monkeypatch.setattr(advisor_job_module, "AdvisorService", _FakeAdvisorService)
    import backend.services.backtest_service as backtest_module

    monkeypatch.setattr(backtest_module, "BacktestService", _FakeBacktestService)
    import smtplib

    monkeypatch.setattr(smtplib, "SMTP_SSL", _FailingSMTP)


def _assert_no_side_effects(db):
    """断言分析、数据库和本地邮件均未发生调用。"""
    assert _FakeAdvisorService.calls == 0
    assert _FakeBacktestService.calls == {
        "validate_due": 0,
        "refresh_hit_rates": 0,
        "get_feedback": 0,
    }
    assert db.add_count == 0
    assert db.query_count == 0
    assert db.commit_count == 0
    assert db.rollback_count == 0
    assert _FailingSMTP.calls == 0


def _normal_result():
    """返回 API 默认路径使用的完整虚构合同。"""
    contract = {
        "operation_scope": "advisor_analysis_with_persistence_and_backtest_updates",
        "read_only": False,
        "report_persistence_enabled": False,
        "backtest_updates_enabled": True,
        "database_writes_possible": True,
        "external_model_calls_enabled": True,
        "local_email_disabled": True,
        "email_owner": "OpenClaw",
    }
    return {
        "success": True,
        "is_fallback": False,
        "analysis": {},
        "email_sent": False,
        "email_owner": "OpenClaw",
        "local_email_disabled": True,
        "skipped": False,
        "summary": contract.copy(),
        **contract,
    }


def test_fixture_a_read_only_fails_before_all_calls(monkeypatch):
    """夹具A：伪只读在分析、数据库、回测和 SMTP 前拒绝。"""
    _patch_services(monkeypatch)
    db = _FakeDB()
    with pytest.raises(ValueError, match="不支持只读模式.*push_email=false 仅关闭本地邮件"):
        AdvisorJob(
            db,
            push_email=False,
            persist_report=False,
            read_only=True,
        ).run()
    _assert_no_side_effects(db)


def test_fixture_b_api_read_only_returns_400_before_calls(monkeypatch):
    """夹具B：API 伪只读请求返回400且不触发任何依赖。"""
    _patch_services(monkeypatch)
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc_info:
        scheduler_api.run_advisor_job(
            read_only=True,
            push_email=False,
            force=False,
            model="test-model",
            db=db,
        )
    assert exc_info.value.status_code == 400
    assert "不支持只读模式" in exc_info.value.detail
    assert "push_email=false 仅关闭本地邮件" in exc_info.value.detail
    _assert_no_side_effects(db)


def test_fixture_c_normal_path_discloses_possible_side_effects(monkeypatch):
    """夹具C：无邮件正常路径保留回测调用并披露数据库/模型可能性。"""
    _patch_services(monkeypatch)
    db = _FakeDB()
    result = AdvisorJob(
        db,
        push_email=False,
        persist_report=False,
        read_only=False,
    ).run()

    assert _FakeAdvisorService.calls == 1
    assert _FakeBacktestService.calls == {
        "validate_due": 1,
        "refresh_hit_rates": 1,
        "get_feedback": 1,
    }
    assert _FailingSMTP.calls == 0
    expected = {
        "operation_scope": "advisor_analysis_with_persistence_and_backtest_updates",
        "read_only": False,
        "report_persistence_enabled": False,
        "backtest_updates_enabled": True,
        "database_writes_possible": True,
        "external_model_calls_enabled": True,
        "local_email_disabled": True,
        "email_owner": "OpenClaw",
    }
    for key, value in expected.items():
        assert result[key] == value
        assert result["summary"][key] == value
    assert result["email_sent"] is False


def test_fixture_d_api_default_is_false_and_source_discloses_scope(monkeypatch):
    """夹具D：省略 read_only 时按 false 传入，路由文案披露真实边界。"""
    captured = {}

    class FakeJob:
        """捕获 API 传入参数并返回虚构合同。"""

        def __init__(self, db, **kwargs):
            captured["db"] = db
            captured.update(kwargs)

        def run(self):
            """返回完整虚构操作合同。"""
            return _normal_result()

    monkeypatch.setattr(advisor_job_module, "AdvisorJob", FakeJob)
    result = scheduler_api.run_advisor_job(
        push_email=False,
        model="test-model",
        force=False,
        db=None,
    )
    assert captured["read_only"] is False
    for key in _normal_result():
        assert key in result

    source = Path(scheduler_api.__file__).read_text(encoding="utf-8")
    for phrase in (
        "不是只读巡检",
        "健康检查",
        "AdvisorReport",
        "AdviceSnapshot",
        "FactorHitRate",
        "外部模型",
    ):
        assert phrase in source

    advisor_source = Path(advisor_job_module.__file__).read_text(encoding="utf-8")
    assert "This job only generates reports" not in advisor_source
    assert "幂等、无副作用" not in advisor_source
    for phrase in (
        "可能持久化报告",
        "可能更新回测统计",
        "可能调用外部模型",
    ):
        assert phrase in advisor_source
