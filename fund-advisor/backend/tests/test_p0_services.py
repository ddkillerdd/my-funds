"""后端盈利链路 P0 服务层测试。

测试使用伪造 Session，不连接本地或服务器数据库。
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.models.advice_snapshot import AdviceSnapshot
from backend.services.advisor_service import AdvisorService
from backend.services.backtest_service import BacktestService


class _FakeResult:
    """提供 SQLAlchemy Result 测试所需的最小接口。"""

    def __init__(self, *, scalar_value=None, items=None):
        self._scalar_value = scalar_value
        self._items = list(items or [])

    # 返回单个聚合值。
    def scalar(self):
        return self._scalar_value

    # 模拟 SQLAlchemy 的 scalars 链式调用。
    def scalars(self):
        return self

    # 返回预设结果列表。
    def all(self):
        return list(self._items)


class _NavSession:
    """记录净值查询语句并返回倒序的最近记录。"""

    def __init__(self, rows):
        self.rows = list(rows)
        self.statement = None

    # 捕获查询语句，模拟数据库按 DESC 返回结果。
    def execute(self, statement):
        self.statement = statement
        return _FakeResult(items=self.rows)


class _ScriptedSession:
    """按照服务调用顺序返回预设查询结果。"""

    def __init__(self, results):
        self._results = iter(results)

    # 返回下一个预设查询结果。
    def execute(self, statement):
        return next(self._results)


# 验证服务查询最新记录，并恢复为时间升序交给指标计算。
def test_load_nav_history_queries_latest_rows_and_returns_ascending():
    rows = [
        SimpleNamespace(nav_date=date(2025, 1, 5), unit_nav=Decimal("1.05")),
        SimpleNamespace(nav_date=date(2025, 1, 4), unit_nav=Decimal("1.04")),
        SimpleNamespace(nav_date=date(2025, 1, 3), unit_nav=Decimal("1.03")),
    ]
    db = _NavSession(rows)
    service = AdvisorService(db)

    history = service._load_nav_history("000001", limit=3)

    assert [point.date for point in history] == [
        "2025-01-03",
        "2025-01-04",
        "2025-01-05",
    ]
    assert [point.nav for point in history] == pytest.approx([1.03, 1.04, 1.05])
    sql = str(db.statement).upper()
    assert "ORDER BY FUND_NAV_HISTORY.NAV_DATE DESC" in sql
    assert "LIMIT" in sql


# 验证 LIMIT 应作用于最新记录，再恢复为完整的时间升序窗口。
def test_load_nav_history_uses_latest_window_not_oldest_rows():
    first = date(2025, 1, 1)
    rows = [
        SimpleNamespace(
            nav_date=first + timedelta(days=i),
            unit_nav=Decimal("1") + Decimal(i) / Decimal("1000"),
        )
        for i in range(299, -1, -1)
    ]
    history = AdvisorService(_NavSession(rows))._load_nav_history("000001", limit=252)

    assert len(history) == 252
    assert history[0].date == (first + timedelta(days=48)).isoformat()
    assert history[-1].date == (first + timedelta(days=299)).isoformat()


# 验证动作快照直接从 FundDiagnosis 的最新净值读取，不依赖不存在的 quant_map。
def test_extract_actions_carries_latest_nav_as_json_number():
    qi = SimpleNamespace(current_nav=Decimal("1.2345"))
    report = SimpleNamespace(
        per_fund_diagnosis=[
            SimpleNamespace(
                fund_code="000001",
                fund_name="合成基金",
                ground_truth=qi,
                debate_summary=SimpleNamespace(action={"action": "buy"}),
            )
        ]
    )

    actions = AdvisorService.__new__(AdvisorService)._extract_actions(report)

    assert actions[0]["nav"] == pytest.approx(1.2345)
    assert isinstance(actions[0]["nav"], float)


# 验证按动作命中率仅使用 hit/miss，neutral 只影响覆盖率。
def test_get_stats_uses_directional_denominator_and_reports_coverage():
    validated_rows = [
        AdviceSnapshot(
            fund_code="F",
            action="buy",
            advice_date=date(2025, 1, 1),
            status="validated",
            verdict="hit",
        ),
        AdviceSnapshot(
            fund_code="F",
            action="buy",
            advice_date=date(2025, 1, 2),
            status="validated",
            verdict="miss",
        ),
        AdviceSnapshot(
            fund_code="F",
            action="buy",
            advice_date=date(2025, 1, 3),
            status="validated",
            verdict="neutral",
        ),
        AdviceSnapshot(
            fund_code="F",
            action="hold",
            advice_date=date(2025, 1, 4),
            status="validated",
            verdict="neutral",
        ),
    ]
    db = _ScriptedSession(
        [
            _FakeResult(scalar_value=4),
            _FakeResult(scalar_value=0),
            _FakeResult(items=validated_rows),
            _FakeResult(items=[]),
            _FakeResult(items=[]),
        ]
    )

    stats = BacktestService(db).get_stats()

    assert stats.directional == 2
    assert stats.hits == 1
    assert stats.miss == 1
    assert stats.neutral == 2
    assert stats.hit_rate == Decimal("0.5")
    assert stats.coverage == Decimal("0.5")
    assert stats.by_action["buy"] == {
        "total": 3,
        "hits": 1,
        "miss": 1,
        "directional": 2,
        "neutral": 1,
        "coverage": pytest.approx(2 / 3, abs=0.0001),
        "hit_rate": 0.5,
    }
    assert stats.by_action["hold"]["directional"] == 0
    assert stats.by_action["hold"]["coverage"] == 0.0
    assert stats.by_action["hold"]["hit_rate"] is None


# 验证历史 add 与当前 increase 会归并到同一方向统计桶。
def test_get_stats_normalizes_legacy_add_action():
    rows = [
        AdviceSnapshot(
            fund_code="F", action="add", advice_date=date(2025, 1, 1),
            status="validated", verdict="hit",
        ),
        AdviceSnapshot(
            fund_code="F", action="increase", advice_date=date(2025, 1, 2),
            status="validated", verdict="miss",
        ),
    ]
    db = _ScriptedSession([
        _FakeResult(scalar_value=2),
        _FakeResult(scalar_value=0),
        _FakeResult(items=rows),
        _FakeResult(items=[]),
        _FakeResult(items=[]),
    ])

    stats = BacktestService(db).get_stats()

    assert set(stats.by_action) == {"increase"}
    assert stats.by_action["increase"]["total"] == 2
    assert stats.by_action["increase"]["directional"] == 2
