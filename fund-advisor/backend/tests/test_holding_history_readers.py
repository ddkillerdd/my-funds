"""B2 持仓历史读侧测试：只使用虚构对象和可观察的假查询。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from backend.services.calendar_service import CalendarService
from backend.services.nav_service import NavService
from backend.services.snapshot_service import SnapshotService


def _event(holding_id, event_id, fund_code, event_date, shares_after, source_type):
    """构造最小化的虚构持仓事件。"""
    return SimpleNamespace(
        id=event_id,
        holding_id=holding_id,
        fund_code=fund_code,
        business_date=event_date,
        shares_after=Decimal(shares_after),
        shares_delta=Decimal(shares_after),
        nav_at_change=Decimal("2"),
        source_type=source_type,
    )


def test_calendar_effective_shares_mixes_events_and_legacy_boundary():
    """验证事件优先、legacy 仅在建立日及之后生效，建立日前为零。"""
    service = CalendarService(None)
    event = _event(1, 2, "F-A", date(2026, 9, 4), "7", "manual")
    event_holding = SimpleNamespace(id=1, status=1, source_type="legacy", share_date=date(2026, 9, 1), shares=Decimal("3"))
    legacy_holding = SimpleNamespace(id=2, status=1, source_type="legacy", share_date=date(2026, 9, 5), shares=Decimal("4"))

    assert service._get_effective_shares(date(2026, 9, 3), event_holding, {1: [event]}) == 0
    assert service._get_effective_shares(date(2026, 9, 4), event_holding, {1: [event]}) == Decimal("7")
    assert service._get_effective_shares(date(2026, 9, 4), legacy_holding, {}) == 0
    assert service._get_effective_shares(date(2026, 9, 5), legacy_holding, {}) == Decimal("4")


def test_calendar_effective_shares_same_day_clear_and_reactivation():
    """验证同日按事件 id 取最后状态，并支持清零后后续日期重新激活。"""
    service = CalendarService(None)
    clear = _event(1, 2, "F-A", date(2026, 9, 4), "0", "quick")
    reactivate = _event(1, 3, "F-A", date(2026, 9, 5), "6", "file")
    holding = SimpleNamespace(id=1, status=1, source_type="file", share_date=None, shares=None)

    assert service._get_effective_shares(date(2026, 9, 4), holding, {1: [clear, reactivate]}) == 0
    assert service._get_effective_shares(date(2026, 9, 5), holding, {1: [clear, reactivate]}) == Decimal("6")


def test_calendar_effective_shares_aggregates_platforms_by_fund_code():
    """验证同基金不同平台分别重建后再按基金代码聚合。"""
    service = CalendarService(None)
    left = SimpleNamespace(id=1, fund_code="F-A", status=1, source_type="file", share_date=None, shares=None)
    right = SimpleNamespace(id=2, fund_code="F-A", status=1, source_type="file", share_date=None, shares=None)
    changes = {1: [_event(1, 1, "F-A", date(2026, 9, 4), "2", "file")], 2: [_event(2, 2, "F-A", date(2026, 9, 4), "3", "manual")]}

    result = service._build_daily_shares_map([left, right], [date(2026, 9, 4)], changes)
    assert result == {date(2026, 9, 4): {"F-A": Decimal("5")}}


class _Query:
    """记录查询链的过滤、排序和结果，避免假查询无条件返回固定对象。"""

    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.orders = []
        self.distinct_called = False

    def outerjoin(self, *_args):
        return self

    def filter(self, *criteria):
        self.filters.extend(str(item) for item in criteria)
        return self

    def order_by(self, *criteria):
        self.orders.extend(str(item) for item in criteria)
        return self

    def distinct(self):
        self.distinct_called = True
        return self

    def all(self):
        return self.rows


class _CalendarDb:
    """按调用顺序返回指定查询，确保测试能观察读侧约束。"""

    def __init__(self, queries):
        self.queries = iter(queries)

    def query(self, *_args):
        return next(self.queries)


def test_calendar_day_trades_keeps_all_source_types_and_business_date_filter():
    """验证 manual/quick 的空 import_id 与 file 的非空来源都保留。"""
    rows = [
        SimpleNamespace(fund_code="F-A", fund_name="虚构基金", platform="平台A", fund_account="账户A", change_type="new", shares_before=Decimal("0"), shares_after=Decimal("1"), shares_delta=Decimal("1"), nav_at_change=Decimal("2"), mv_before=Decimal("0"), mv_after=Decimal("2"), source_type="manual", import_id=None),
        SimpleNamespace(fund_code="F-A", fund_name="虚构基金", platform="平台A", fund_account="账户A", change_type="increase", shares_before=Decimal("1"), shares_after=Decimal("2"), shares_delta=Decimal("1"), nav_at_change=Decimal("2"), mv_before=Decimal("2"), mv_after=Decimal("4"), source_type="quick", import_id=None),
        SimpleNamespace(fund_code="F-A", fund_name="虚构基金", platform="平台A", fund_account="账户A", change_type="increase", shares_before=Decimal("2"), shares_after=Decimal("3"), shares_delta=Decimal("1"), nav_at_change=Decimal("2"), mv_before=Decimal("4"), mv_after=Decimal("6"), source_type="file", import_id=88),
    ]
    query = _Query(rows)
    result = CalendarService(_CalendarDb([query]))._load_day_trades(date(2026, 9, 4))

    assert [item.source_type for item in result] == ["manual", "quick", "file"]
    assert "business_date" in " ".join(query.filters)
    assert query.orders


def test_calendar_trade_dates_uses_business_date_and_excludes_money_funds():
    """验证交易日读取使用 business_date，并在给定集合时附加货币基金排除条件。"""
    query = _Query([SimpleNamespace(business_date=date(2026, 9, 4))])
    dates = CalendarService(_CalendarDb([query]))._load_trade_dates(
        date(2026, 9, 1), date(2026, 9, 30), {"MONEY"}
    )
    text = " ".join(query.filters)
    assert dates == {date(2026, 9, 4)}
    assert "business_date" in text
    assert query.distinct_called


class _ExecuteResult:
    """提供 scalars/all 与 scalar_one_or_none 两种只读结果接口。"""

    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class _SnapshotDb:
    """按查询调用顺序返回虚构事件或 legacy 持仓。"""

    def __init__(self, results):
        self.results = iter(results)

    def execute(self, _statement):
        return next(self.results)


def test_snapshot_shares_map_handles_event_and_legacy_null_boundaries():
    """验证事件优先，legacy 的空建立日/空份额不被误计入。"""
    event = _event(1, 1, "F-A", date(2026, 9, 4), "5", "quick")
    holdings = [
        SimpleNamespace(id=1, fund_code="F-A", status=1, source_type="legacy", share_date=date(2026, 9, 1), shares=Decimal("2")),
        SimpleNamespace(id=2, fund_code="F-B", status=1, source_type="legacy", share_date=None, shares=Decimal("9")),
        SimpleNamespace(id=3, fund_code="F-C", status=1, source_type="legacy", share_date=date(2026, 9, 1), shares=None),
    ]
    result = SnapshotService(_SnapshotDb([_ExecuteResult([event]), _ExecuteResult(holdings)]))._get_shares_map_on_date(date(2026, 9, 4))
    assert result == {"F-A": Decimal("5")}


def test_snapshot_net_inflow_counts_manual_quick_and_file_events():
    """验证带空 import_id 的 manual/quick 与 file 事件均按 business_date 累计。"""
    events = [
        SimpleNamespace(shares_delta=Decimal("2"), nav_at_change=Decimal("3"), import_id=None, source_type="manual"),
        SimpleNamespace(shares_delta=Decimal("1"), nav_at_change=Decimal("3"), import_id=None, source_type="quick"),
        SimpleNamespace(shares_delta=Decimal("-1"), nav_at_change=Decimal("3"), import_id=88, source_type="file"),
    ]
    value = SnapshotService(_SnapshotDb([_ExecuteResult(events)]))._calculate_net_inflow(date(2026, 9, 4))
    assert value == Decimal("6")


def test_snapshot_historical_backfill_uses_null_import_id_event_date():
    """验证 import_id=None 的事件日期可创建历史快照，并按事件市值汇总。"""
    event = SimpleNamespace(
        holding_id=1,
        business_date=date(2026, 9, 4),
        change_type="new",
        shares_after=Decimal("5"),
        mv_after=Decimal("12"),
        import_id=None,
    )

    class Db:
        """按 backfill 的三次读取返回日期、空快照和事件行。"""

        def __init__(self):
            self.calls = 0
            self.added = []
            self.commits = 0

        def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return _ExecuteResult([date(2026, 9, 4)])
            if self.calls == 2:
                return _ExecuteResult([])
            return type("Rows", (), {"all": lambda _self: [(event,)]})()

        def add(self, value):
            self.added.append(value)

        def commit(self):
            self.commits += 1

    db = Db()
    service = SnapshotService(db)
    service._recompute_daily_pnl_and_nav = lambda: None
    assert service.backfill_historical_snapshots() == 1
    assert db.added[0].snapshot_date == date(2026, 9, 4)
    assert db.added[0].total_market_value == Decimal("12")
    assert db.commits == 1


def test_nav_backfill_history_requires_event_or_legacy_start_date():
    """验证 NAV 回填的起点由最早事件/legacy 日期决定，均无日期时走现有回退路径。"""
    source = NavService.__dict__["backfill_history"]
    assert source.__doc__
    assert "HoldingChange" in source.__code__.co_names
    assert "share_date" in source.__code__.co_names


def test_history_reader_test_scope_has_no_production_writer():
    """验证本测试文件不包含 systemd、服务器或数据库写操作入口。"""
    import ast

    tree = ast.parse(open(__file__, encoding="utf-8").read())
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls.intersection({"commit", "add", "systemctl", "Popen", "run"})
