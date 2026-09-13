"""AdvisorJob 本地邮件禁用边界的合成测试。"""

import inspect

import pytest
from fastapi import HTTPException

import backend.api.scheduler as scheduler_api
import backend.scheduler.advisor_job as advisor_job_module
from backend.scheduler.advisor_job import AdvisorJob


class _FakeDB:
    """记录数据库副作用的虚构 Session。"""

    def __init__(self):
        self.add_count = 0
        self.commit_count = 0
        self.query_count = 0

    def add(self, obj):
        """记录新增对象。"""
        self.add_count += 1

    def commit(self):
        """记录提交次数。"""
        self.commit_count += 1

    def query(self, *args, **kwargs):
        """提供旧去重逻辑所需的最小查询接口。"""
        self.query_count += 1
        return self

    def filter(self, *args, **kwargs):
        """返回可继续调用 first 的虚构查询。"""
        return self

    def first(self):
        """表示没有历史发送记录。"""
        return None


class _FakeAdvisorService:
    """返回最小虚构成功报告并记录分析次数。"""

    calls = 0

    def __init__(self, db):
        self.db = db

    def analyze(self, model=None):
        """返回非降级的虚构分析结果。"""
        type(self).calls += 1
        return {
            "model": model or "test-model",
            "portfolio_diagnosis": {"overall_assessment": "合成分析完成"},
            "holdings_health": [],
            "actions": [],
        }


class _FakeBacktestService:
    """隔离每日回测适应链，避免真实数据库和外部服务。"""

    def __init__(self, db):
        self.db = db

    def validate_due(self):
        """返回没有待验证样本。"""
        return 0

    def refresh_hit_rates(self, rolling_window=10):
        """返回没有适应变更。"""
        return 0

    def get_feedback(self):
        """返回最小虚构反馈。"""
        return type(
            "Feedback",
            (),
            {"has_evidence": False, "prompt_hint": ""},
        )()


class _FailingSMTP:
    """一旦被调用就失败的 SMTP 保护桩。"""

    calls = 0

    def __init__(self, *args, **kwargs):
        type(self).calls += 1
        raise AssertionError("本地邮件链不应构造 SMTP")


def _patch_normal_path(monkeypatch):
    """隔离正常报告路径中的分析、回测和 SMTP。"""
    _FakeAdvisorService.calls = 0
    _FailingSMTP.calls = 0
    monkeypatch.setattr(
        advisor_job_module,
        "AdvisorService",
        _FakeAdvisorService,
    )
    import backend.services.backtest_service as backtest_module
    monkeypatch.setattr(
        backtest_module,
        "BacktestService",
        _FakeBacktestService,
    )
    import smtplib
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FailingSMTP)


def test_fixture_a_defaults_to_no_email_and_reports_openclaw_owner(monkeypatch):
    """夹具A：默认不发邮件且明确由OpenClaw负责邮件。"""
    push_default = inspect.signature(AdvisorJob).parameters["push_email"].default
    api_default = inspect.signature(
        scheduler_api.run_advisor_job
    ).parameters["push_email"].default
    assert push_default is False
    assert getattr(api_default, "default", api_default) is False

    _patch_normal_path(monkeypatch)
    result = AdvisorJob(
        _FakeDB(),
        persist_report=False,
    ).run()

    assert result["email_sent"] is False
    assert result["email_owner"] == "OpenClaw"
    assert result["local_email_disabled"] is True
    assert _FakeAdvisorService.calls == 1
    assert _FailingSMTP.calls == 0


def test_fixture_b_explicit_email_is_rejected_before_analysis_or_writes(monkeypatch):
    """夹具B：push_email=True在分析、持久化和SMTP前拒绝。"""
    _FakeAdvisorService.calls = 0
    db = _FakeDB()
    monkeypatch.setattr(advisor_job_module, "AdvisorService", _FakeAdvisorService)

    with pytest.raises(ValueError, match="本地邮件已禁用.*OpenClaw"):
        AdvisorJob(db, push_email=True, persist_report=False).run()

    assert _FakeAdvisorService.calls == 0
    assert db.add_count == 0
    assert db.commit_count == 0
    assert db.query_count == 0


def test_fixture_c_force_cannot_bypass_local_email_boundary(monkeypatch):
    """夹具C：force=True即使push_email=False也必须前置拒绝。"""
    _FakeAdvisorService.calls = 0
    db = _FakeDB()
    monkeypatch.setattr(advisor_job_module, "AdvisorService", _FakeAdvisorService)

    with pytest.raises(ValueError, match="本地邮件已禁用.*OpenClaw"):
        AdvisorJob(
            db,
            push_email=False,
            force=True,
            persist_report=False,
        ).run()

    assert _FakeAdvisorService.calls == 0
    assert db.add_count == 0
    assert db.commit_count == 0
    assert db.query_count == 0


@pytest.mark.parametrize(
    "push_email,force",
    [(True, False), (False, True)],
)
def test_fixture_d_api_returns_http_400_with_boundary_detail(
    monkeypatch, push_email, force
):
    """夹具D：两类本地邮件请求均映射为HTTP 400并保留说明。"""
    detail = "本地邮件已禁用；邮件责任属于 OpenClaw"

    def reject(self):
        """模拟作业层拒绝本地邮件请求。"""
        raise ValueError(detail)

    monkeypatch.setattr(AdvisorJob, "run", reject)

    with pytest.raises(HTTPException) as exc_info:
        scheduler_api.run_advisor_job(
            push_email=push_email,
            model="test-model",
            force=force,
            db=None,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == detail


def test_fixture_e_normal_report_path_is_retained_without_smtp(monkeypatch):
    """夹具E：正常无邮件运行仍完成分析并返回责任字段。"""
    _patch_normal_path(monkeypatch)
    db = _FakeDB()
    result = AdvisorJob(
        db,
        push_email=False,
        force=False,
        persist_report=False,
    ).run()

    assert result["success"] is True
    assert result["analysis"]["portfolio_diagnosis"]["overall_assessment"] == "合成分析完成"
    assert result["email_sent"] is False
    assert result["email_owner"] == "OpenClaw"
    assert result["local_email_disabled"] is True
    assert _FakeAdvisorService.calls == 1
    assert _FailingSMTP.calls == 0
