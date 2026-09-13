"""无快照历史盈亏的本地合成测试。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database import Base
from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.holding_change import HoldingChange
from backend.models.nav_history import FundNavHistory
from backend.services.analysis_service import AnalysisService


D1 = date(2026, 1, 2)
D2 = date(2026, 1, 5)
D3 = date(2026, 1, 6)


@pytest.fixture
def db():
    """创建只存在于内存中的 ORM 会话。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        Fund.__table__,
        FundHolding.__table__,
        HoldingChange.__table__,
        FundNavHistory.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _fund(code: str, name: str = "虚构基金") -> Fund:
    """创建一个虚构的非货币基金。"""
    return Fund(
        id=abs(hash(code)) % 1000000 + 1,
        fund_code=code,
        fund_name=name,
        fund_type="股票型",
        status=1,
    )


def _holding(
    holding_id: int,
    code: str,
    platform: str,
    shares: str,
    share_date: date,
    status: int = 1,
    source_type: str = "file",
) -> FundHolding:
    """创建一个虚构平台持仓。"""
    return FundHolding(
        id=holding_id,
        fund_code=code,
        fund_name="虚构基金",
        platform=platform,
        fund_account=f"账户{holding_id}",
        trade_account=f"交易{holding_id}",
        shares=Decimal(shares),
        share_date=share_date,
        source_type=source_type,
        status=status,
    )


def _change(
    change_id: int,
    holding_id: int,
    code: str,
    when: date,
    before: str,
    after: str,
    delta: str | None,
    nav: str | None,
) -> HoldingChange:
    """创建一条虚构的持仓变动事件。"""
    return HoldingChange(
        id=change_id,
        holding_id=holding_id,
        fund_code=code,
        fund_name="虚构基金",
        platform="虚构平台",
        change_type="increase" if Decimal(after) >= Decimal(before) else "decrease",
        shares_before=Decimal(before),
        shares_after=Decimal(after),
        shares_delta=Decimal(delta) if delta is not None else None,
        nav_at_change=Decimal(nav) if nav is not None else None,
        mv_before=None,
        mv_after=None,
        business_date=when,
        source_type="file",
    )


def _nav(nav_id: int, code: str, when: date, value: str) -> FundNavHistory:
    """创建一条虚构的历史净值。"""
    return FundNavHistory(
        id=nav_id,
        fund_code=code,
        nav_date=when,
        unit_nav=Decimal(value),
    )


def _service_with_core_fixture(db: Session) -> AnalysisService:
    """构造包含跨平台、分批申购和缺当天净值的核心夹具。"""
    db.add_all([
        _fund("F-A"),
        _fund("F-B"),
        _holding(1, "F-A", "平台P", "200", D3),
        _holding(2, "F-A", "平台Q", "50", D2),
        _holding(3, "F-B", "平台P", "10", D1),
        _change(1, 1, "F-A", D1, "0", "100", "100", "1.00"),
        _change(2, 2, "F-A", D2, "0", "50", "50", "1.10"),
        _change(3, 1, "F-A", D3, "100", "200", "100", "1.20"),
        _change(4, 3, "F-B", D1, "0", "10", "10", "10.00"),
        _nav(1, "F-A", D1, "1.00"),
        _nav(2, "F-A", D2, "1.10"),
        _nav(3, "F-A", D3, "1.20"),
        _nav(4, "F-B", D1, "10.00"),
        _nav(5, "F-B", D3, "11.00"),
    ])
    db.flush()
    return AnalysisService(db)


def _points_by_date(service: AnalysisService):
    """读取核心夹具的每日结果并按日期索引。"""
    return {
        point.pnl_date: point
        for point in service._period_detail_no_import(D1, D3)
    }


def test_history_pnl_uses_historical_shares_nav_carry_and_cash_flow(db):
    """验证核心夹具的历史份额、缺净值回填和资金流剔除。"""
    service = _service_with_core_fixture(db)

    core = service._build_no_snapshot_result(["F-A", "F-B"], D1, D3)
    points = _points_by_date(service)
    total_pnl, trading_days = service._calc_pnl_range_no_import(
        ["F-A", "F-B"], D1, D3
    )
    summaries = {
        item.fund_code: item
        for item in service._fund_pnl_no_import(D1, D3)
    }

    assert core.fund_days["F-A"][D1].shares == Decimal("100")
    assert core.fund_days["F-A"][D2].shares == Decimal("150")
    assert core.fund_days["F-A"][D3].shares == Decimal("250")
    assert core.fund_days["F-B"][D2].market_value == Decimal("100")
    assert points[D2].total_mv == Decimal("265")
    assert points[D2].total_pnl == Decimal("10")
    assert points[D3].total_mv == Decimal("410")
    assert points[D3].total_pnl == Decimal("25")
    assert total_pnl == Decimal("35")
    assert trading_days == 2
    assert summaries["F-A"].period_pnl == Decimal("25")
    assert summaries["F-B"].period_pnl == Decimal("10")
    assert summaries["F-A"].platform == "平台P、平台Q"
    assert summaries["F-A"].period_pnl_pct is None
    assert summaries["F-B"].period_pnl_pct == Decimal("10")
    assert sum(point.total_pnl for point in points.values()) == total_pnl
    assert sum(item.period_pnl for item in summaries.values()) == total_pnl


def test_history_pnl_excludes_redemption_and_full_redemption_cash_flow(db):
    """验证卖出和全赎回不被当成亏损。"""
    db.add_all([
        _fund("SELL"),
        _holding(10, "SELL", "平台A", "0", D3, status=0),
        _change(10, 10, "SELL", D1, "0", "200", "200", "1.00"),
        _change(11, 10, "SELL", D2, "200", "100", "-100", "1.10"),
        _change(12, 10, "SELL", D3, "100", "0", "-100", "1.20"),
        _nav(10, "SELL", D1, "1.00"),
        _nav(11, "SELL", D2, "1.10"),
        _nav(12, "SELL", D3, "1.20"),
    ])
    db.flush()
    points = _points_by_date(AnalysisService(db))
    assert points[D2].total_pnl == Decimal("20")
    assert points[D3].total_pnl == Decimal("10")


def test_history_pnl_legacy_initial_snapshot_only_sets_baseline(db):
    """验证 legacy 初始快照不倒造建立日前收益。"""
    db.add_all([
        _fund("LEGACY"),
        _holding(11, "LEGACY", "平台A", "100", D2, source_type="legacy"),
        _nav(13, "LEGACY", D1, "1.00"),
        _nav(14, "LEGACY", D2, "2.00"),
        _nav(15, "LEGACY", D3, "3.00"),
    ])
    db.flush()
    service = AnalysisService(db)
    points = _points_by_date(service)
    summary = service._fund_pnl_no_import(D1, D3)[0]
    _, trading_days = service._calc_pnl_range_no_import(["LEGACY"], D1, D3)
    assert points[D2].total_pnl is None
    assert points[D3].total_pnl == Decimal("100")
    assert summary.period_pnl == Decimal("100")
    assert trading_days == 1


def test_history_pnl_without_period_start_nav_builds_later_baseline(db):
    """验证没有期初净值时不推测首日价值。"""
    db.add_all([
        _fund("NO_START"),
        _holding(12, "NO_START", "平台A", "10", D1),
        _change(13, 12, "NO_START", D1, "0", "10", "10", "2.00"),
        _nav(16, "NO_START", D2, "2.00"),
        _nav(17, "NO_START", D3, "3.00"),
    ])
    db.flush()
    service = AnalysisService(db)
    summary = service._fund_pnl_no_import(D1, D3)[0]
    assert summary.period_pnl == Decimal("10")
    assert summary.start_mv == Decimal("20")


def test_history_pnl_missing_trade_nav_is_not_guessed(db):
    """验证缺少变动净值时返回不可计算语义。"""
    db.add_all([
        _fund("NO_TRADE_NAV"),
        _holding(13, "NO_TRADE_NAV", "平台A", "200", D3),
        _change(14, 13, "NO_TRADE_NAV", D1, "0", "100", "100", "1.00"),
        _change(15, 13, "NO_TRADE_NAV", D2, "100", "200", "100", None),
        _nav(18, "NO_TRADE_NAV", D1, "1.00"),
        _nav(19, "NO_TRADE_NAV", D2, "1.10"),
        _nav(20, "NO_TRADE_NAV", D3, "1.20"),
    ])
    db.flush()
    service = AnalysisService(db)
    points = _points_by_date(service)
    summary = service._fund_pnl_no_import(D1, D3)[0]
    total_pnl, trading_days = service._calc_pnl_range_no_import(
        ["NO_TRADE_NAV"], D1, D3
    )
    assert points[D2].total_pnl is None
    assert summary.period_pnl is None
    assert total_pnl is None
    assert trading_days == 1


def test_history_pnl_orders_same_day_events_and_keeps_platforms(db):
    """验证同日事件按 id 排序并保留多平台持仓聚合。"""
    db.add_all([
        _fund("ORDER"),
        _holding(14, "ORDER", "平台A", "20", D1),
        _holding(15, "ORDER", "平台B", "30", D1),
        _change(16, 14, "ORDER", D1, "0", "10", "10", "1.00"),
        _change(17, 14, "ORDER", D1, "10", "20", "10", "1.00"),
        _change(18, 15, "ORDER", D1, "0", "30", "30", "1.00"),
        _nav(21, "ORDER", D1, "1.00"),
        _nav(22, "ORDER", D2, "2.00"),
        _nav(23, "ORDER", D3, "3.00"),
    ])
    db.flush()
    service = AnalysisService(db)
    points = _points_by_date(service)
    summary = service._fund_pnl_no_import(D1, D3)[0]
    assert points[D2].total_mv == Decimal("100")
    assert summary.shares == Decimal("50")
    assert summary.period_pnl == Decimal("100")


def test_trading_days_excludes_event_only_date_without_new_nav(db):
    """验证只有持仓事件而无当日新净值的日期不计入交易日。"""
    db.add_all([
        _fund("EVENT_ONLY"),
        _holding(16, "EVENT_ONLY", "平台A", "200", D2),
        _change(19, 16, "EVENT_ONLY", D1, "0", "100", "100", "1.00"),
        _change(20, 16, "EVENT_ONLY", D2, "100", "200", "100", "1.00"),
        _nav(24, "EVENT_ONLY", D1, "1.00"),
        _nav(25, "EVENT_ONLY", D3, "1.10"),
    ])
    db.flush()
    service = AnalysisService(db)
    total_pnl, trading_days = service._calc_pnl_range_no_import(
        ["EVENT_ONLY"], D1, D3
    )
    assert total_pnl == Decimal("20")
    assert trading_days == 1
