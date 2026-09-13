"""F08A 调度时区、周末入口防线和工作日行为合成测试。"""

import asyncio
from datetime import datetime

import pytest

import backend.scheduler.jobs as jobs


def _trigger_field(trigger, name):
    """按字段名称读取 CronTrigger 字段。"""
    return next(field for field in trigger.fields if field.name == name)


def test_fixture_a_scheduler_uses_explicit_shanghai_timezone():
    """夹具A：模块和调度器共享显式的上海时区对象。"""
    assert jobs.SCHEDULER_TIMEZONE.key == "Asia/Shanghai"
    assert jobs.scheduler.timezone == jobs.SCHEDULER_TIMEZONE


def test_fixture_b_three_cron_jobs_inherit_same_timezone_and_window():
    """夹具B：三个候选窗口保持原 job id、时间和工作日表达。"""
    jobs.scheduler.remove_all_jobs()
    try:
        configured = jobs.setup_scheduler()
        expected = {
            "refresh_nav": (20, 0),
            "retry_nav": (22, 0),
            "daily_snapshot": (22, 30),
        }
        for job_id, (hour, minute) in expected.items():
            job = configured.get_job(job_id)
            assert job is not None
            assert job.trigger.timezone.key == "Asia/Shanghai"
            assert str(_trigger_field(job.trigger, "day_of_week")) == "mon-fri"
            assert str(_trigger_field(job.trigger, "hour")) == str(hour)
            assert str(_trigger_field(job.trigger, "minute")) == str(minute)
    finally:
        jobs.scheduler.remove_all_jobs()


def test_fixture_c_weekend_short_circuits_before_session(monkeypatch):
    """夹具C：上海周末直接调用时在创建数据库会话前短路。"""
    saturday = datetime(
        2026,
        9,
        12,
        10,
        0,
        tzinfo=jobs.SCHEDULER_TIMEZONE,
    )
    sunday = datetime(
        2026,
        9,
        13,
        10,
        0,
        tzinfo=jobs.SCHEDULER_TIMEZONE,
    )
    session_calls = 0
    service_calls = {"nav": 0, "snapshot": 0}

    def fail_session():
        """数据库会话桩不应在周末入口被调用。"""
        nonlocal session_calls
        session_calls += 1
        raise AssertionError("周末不应创建数据库会话")

    class FailNavService:
        """净值服务桩不应在周末入口被实例化。"""

        def __init__(self, db):
            service_calls["nav"] += 1
            raise AssertionError("周末不应实例化净值服务")

    class FailSnapshotService:
        """快照服务桩不应在周末入口被实例化。"""

        def __init__(self, db):
            service_calls["snapshot"] += 1
            raise AssertionError("周末不应实例化快照服务")

    monkeypatch.setattr(jobs, "SessionLocal", fail_session)
    monkeypatch.setattr(jobs, "NavService", FailNavService)
    monkeypatch.setattr(jobs, "SnapshotService", FailSnapshotService)

    for current in (saturday, sunday):
        monkeypatch.setattr(jobs, "_scheduler_now", lambda current=current: current)
        asyncio.run(jobs.job_refresh_nav())
        asyncio.run(jobs.job_retry_nav())
        asyncio.run(jobs.job_daily_snapshot())

    assert session_calls == 0
    assert service_calls == {"nav": 0, "snapshot": 0}


def test_fixture_d_weekday_keeps_refresh_retry_and_snapshot_calls(monkeypatch):
    """夹具D：上海普通周三仍执行原有三条服务调用并关闭会话。"""
    wednesday = datetime(
        2026,
        9,
        9,
        10,
        0,
        tzinfo=jobs.SCHEDULER_TIMEZONE,
    )
    monkeypatch.setattr(jobs, "_scheduler_now", lambda: wednesday)
    sessions = []
    calls = {"refresh": 0, "snapshot": 0}

    class FakeSession:
        """记录工作日任务的关闭行为。"""

        def close(self):
            """记录会话关闭。"""
            self.closed = True

    def make_session():
        """创建虚构数据库会话。"""
        session = FakeSession()
        session.closed = False
        sessions.append(session)
        return session

    class FakeNavService:
        """记录两次净值刷新任务调用。"""

        def __init__(self, db):
            self.db = db

        async def refresh_all_nav_smart(self):
            """记录一次智能净值刷新。"""
            calls["refresh"] += 1
            return {"updated": 0}

    class FakeSnapshot:
        """提供最小虚构快照结果。"""

        snapshot_date = "2026-09-09"
        total_market_value = 100.0

    class FakeSnapshotService:
        """记录一次日快照调用。"""

        def __init__(self, db):
            self.db = db

        def create_daily_snapshot(self):
            """记录一次日快照创建。"""
            calls["snapshot"] += 1
            return FakeSnapshot()

    monkeypatch.setattr(jobs, "SessionLocal", make_session)
    monkeypatch.setattr(jobs, "NavService", FakeNavService)
    monkeypatch.setattr(jobs, "SnapshotService", FakeSnapshotService)

    asyncio.run(jobs.job_refresh_nav())
    asyncio.run(jobs.job_retry_nav())
    asyncio.run(jobs.job_daily_snapshot())

    assert calls == {"refresh": 2, "snapshot": 1}
    assert len(sessions) == 3
    assert all(session.closed for session in sessions)
