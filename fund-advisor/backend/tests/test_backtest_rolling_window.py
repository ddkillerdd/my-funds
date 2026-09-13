"""回测命中率最近 N 条 validated 样本的纯合成测试。"""

from datetime import date, timedelta

import pytest

from backend.models.advice_snapshot import AdviceSnapshot
from backend.services.backtest_service import BacktestService


class _FakeResult:
    """提供回测服务所需的最小 SQLAlchemy Result 接口。"""

    def __init__(self, *, items=None, scalar_value=None):
        self._items = list(items or [])
        self._scalar_value = scalar_value

    # 返回模拟的标量查询结果。
    def scalar_one_or_none(self):
        return self._scalar_value

    # 返回模拟的列表查询结果。
    def scalars(self):
        return self

    # 返回预设的实体列表。
    def all(self):
        return list(self._items)


class _FakeSession:
    """只在内存中返回快照并记录命中率写回。"""

    def __init__(self, validated_rows):
        self.validated_rows = list(validated_rows)
        self.factor_rows = {}
        self.added = []
        self.execute_count = 0
        self.commit_count = 0

    # 根据查询类型返回快照或已有统计桶。
    def execute(self, statement):
        self.execute_count += 1
        entity = statement.column_descriptions[0].get("entity")
        if entity is AdviceSnapshot:
            return _FakeResult(items=self.validated_rows)

        params = statement.compile().params
        factor_key = next(
            value for key, value in params.items() if key.startswith("factor_key")
        )
        action_type = next(
            value for key, value in params.items() if key.startswith("action_type")
        )
        return _FakeResult(
            scalar_value=self.factor_rows.get((factor_key, action_type))
        )

    # 记录新增统计行并让后续刷新可以复用该行。
    def add(self, row):
        self.added.append(row)
        self.factor_rows[(row.factor_key, row.action_type)] = row

    # 记录正常事务提交次数。
    def commit(self):
        self.commit_count += 1


def _snapshot(row_id, advice_date, action, verdict):
    """创建带有显式主键和日期的虚构已验证快照。"""
    return AdviceSnapshot(
        id=row_id,
        fund_code="F12B",
        action=action,
        advice_date=advice_date,
        status="validated",
        verdict=verdict,
    )


def _stats_by_key(session):
    """将内存中的统计行按因子和动作类型建立索引。"""
    return {
        (row.factor_key, row.action_type): row
        for row in session.factor_rows.values()
    }


def test_recent_window_rejects_old_cumulative_50_percent_result():
    """验证乱序的早期命中不会混入最近十条全为 miss 的窗口。"""
    start = date(2025, 1, 1)
    rows = [
        _snapshot(
            row_id,
            start + timedelta(days=row_id - 1),
            "increase",
            "hit" if row_id <= 10 else "miss",
        )
        for row_id in range(1, 21)
    ]
    session = _FakeSession(list(reversed(rows)))

    updated = BacktestService(session).refresh_hit_rates(rolling_window=10)

    assert updated == 2
    stats = _stats_by_key(session)
    actual = {
        key: (
            stats[key].hits,
            stats[key].miss,
            stats[key].total,
            stats[key].hit_rate,
        )
        for key in (("increase", "action"), ("all", "overall"))
    }
    assert actual == {
        ("increase", "action"): (0, 10, 10, 0.0),
        ("all", "overall"): (0, 10, 10, 0.0),
    }
    assert all(stats[key].rolling_window == 10 for key in actual)


def test_action_buckets_use_independent_windows():
    """验证稀有动作不会被 overall 窗口吞掉。"""
    start = date(2025, 2, 1)
    rows = [
        _snapshot(1, start, "increase", "hit"),
        _snapshot(2, start, "increase", "miss"),
        _snapshot(3, start + timedelta(days=1), "hold", "neutral"),
        _snapshot(4, start + timedelta(days=2), "increase", "miss"),
        _snapshot(5, start + timedelta(days=3), "reduce", "hit"),
        _snapshot(6, start + timedelta(days=4), "increase", "miss"),
    ]
    session = _FakeSession(
        [rows[5], rows[0], rows[2], rows[1], rows[4], rows[3]]
    )

    BacktestService(session).refresh_hit_rates(rolling_window=2)

    stats = _stats_by_key(session)
    buy = stats[("increase", "action")]
    reduce = stats[("reduce", "action")]
    overall = stats[("all", "overall")]
    assert (buy.hits, buy.miss, buy.total) == (0, 2, 2)
    assert (reduce.hits, reduce.miss, reduce.total) == (1, 0, 1)
    assert (overall.hits, overall.miss, overall.total) == (1, 1, 2)
    assert all(row.rolling_window == 2 for row in stats.values())


def test_same_day_larger_id_is_newer():
    """验证同日记录按更大的主键 id 作为最近记录。"""
    same_day = date(2025, 2, 1)
    rows = [
        _snapshot(10, same_day, "increase", "hit"),
        _snapshot(11, same_day, "increase", "miss"),
    ]
    session = _FakeSession([rows[0], rows[1]])

    BacktestService(session).refresh_hit_rates(rolling_window=1)

    stats = _stats_by_key(session)
    row = stats[("increase", "action")]
    assert (row.hits, row.miss, row.total, row.hit_rate) == (0, 1, 1, 0.0)
    assert row.rolling_window == 1


def test_add_and_increase_share_normalized_action_window():
    """验证历史 add 与 increase 在标准化后的同一动作桶中取窗。"""
    start = date(2025, 3, 1)
    rows = [
        _snapshot(1, start, "add", "hit"),
        _snapshot(2, start + timedelta(days=1), "add", "hit"),
        _snapshot(3, start + timedelta(days=2), "increase", "miss"),
        _snapshot(4, start + timedelta(days=3), "increase", "miss"),
    ]
    session = _FakeSession([rows[1], rows[3], rows[0], rows[2]])

    BacktestService(session).refresh_hit_rates(rolling_window=2)

    stats = _stats_by_key(session)
    assert set(key for key in stats if key[1] == "action") == {("increase", "action")}
    row = stats[("increase", "action")]
    assert (row.hits, row.miss, row.total, row.hit_rate) == (0, 2, 2, 0.0)
    assert row.rolling_window == 2


def test_neutral_consumes_window_but_not_directional_denominator():
    """验证 neutral 占窗口位置，纯 neutral 则没有方向命中率。"""
    start = date(2025, 4, 1)
    rows = [
        _snapshot(1, start, "increase", "hit"),
        _snapshot(2, start + timedelta(days=1), "increase", "neutral"),
        _snapshot(3, start + timedelta(days=2), "increase", "miss"),
        _snapshot(4, start + timedelta(days=3), "hold", "neutral"),
        _snapshot(5, start + timedelta(days=4), "hold", "neutral"),
    ]
    session = _FakeSession(list(reversed(rows)))

    BacktestService(session).refresh_hit_rates(rolling_window=2)

    stats = _stats_by_key(session)
    buy = stats[("increase", "action")]
    hold = stats[("hold", "action")]
    assert (buy.hits, buy.miss, buy.total, buy.hit_rate) == (0, 1, 1, 0.0)
    assert (hold.hits, hold.miss, hold.total, hold.hit_rate) == (0, 0, 0, None)
    assert all(row.rolling_window == 2 for row in stats.values())


def test_fewer_than_window_uses_all_samples_and_empty_commits_once_without_add():
    """验证不足窗口使用全部样本，空样本不写行但正常提交一次。"""
    rows = [
        _snapshot(1, date(2025, 5, 1), "increase", "hit"),
        _snapshot(2, date(2025, 5, 2), "increase", "miss"),
    ]
    session = _FakeSession(rows)

    updated = BacktestService(session).refresh_hit_rates(rolling_window=10)

    assert updated == 2
    row = _stats_by_key(session)[("increase", "action")]
    assert (row.hits, row.miss, row.total) == (1, 1, 2)
    assert row.rolling_window == 10

    empty = _FakeSession([])
    assert BacktestService(empty).refresh_hit_rates(rolling_window=10) == 0
    assert empty.added == []
    assert empty.commit_count == 1


def test_repeated_refresh_updates_existing_rows_without_duplicate_buckets():
    """验证重复刷新复用相同统计行而不新增重复桶。"""
    rows = [
        _snapshot(1, date(2025, 6, 1), "increase", "hit"),
        _snapshot(2, date(2025, 6, 2), "increase", "miss"),
    ]
    session = _FakeSession(rows)
    service = BacktestService(session)

    assert service.refresh_hit_rates(rolling_window=2) == 2
    first_rows = dict(session.factor_rows)
    assert service.refresh_hit_rates(rolling_window=2) == 2

    assert len(session.added) == 2
    assert session.factor_rows == first_rows
    assert len(set(session.factor_rows)) == 2
    assert session.commit_count == 2


@pytest.mark.parametrize("invalid_window", [0, -1, True, "10", 1.5])
def test_invalid_window_fails_before_any_session_side_effect(invalid_window):
    """验证无效窗口在 execute、add 和 commit 前统一抛出 ValueError。"""
    session = _FakeSession([])

    with pytest.raises(ValueError):
        BacktestService(session).refresh_hit_rates(rolling_window=invalid_window)

    assert session.execute_count == 0
    assert session.added == []
    assert session.commit_count == 0
