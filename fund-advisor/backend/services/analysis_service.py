"""Analysis service - period PnL analysis between imports."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.holding_change import HoldingChange
from backend.models.holding_daily_pnl import HoldingDailyPnL
from backend.models.import_record import ImportRecord
from backend.models.nav_history import FundNavHistory
from backend.schemas.holding_daily_pnl import (
    PeriodItem,
    FundPnLSummary,
    DailyPnLPoint,
)


@dataclass
class _NoSnapshotFundDay:
    """保存无快照回退中单基金某日的估值结果。"""

    shares: Decimal
    market_value: Optional[Decimal]
    daily_pnl: Optional[Decimal] = None


@dataclass
class _NoSnapshotResult:
    """保存三个无快照回退共享的历史计算结果。"""

    dates: list[date]
    fund_codes: list[str]
    fund_days: dict[str, dict[date, _NoSnapshotFundDay]]
    total_market_value: dict[date, Optional[Decimal]]
    total_daily_pnl: dict[date, Optional[Decimal]]
    fund_period_pnl: dict[str, Optional[Decimal]]
    fund_start_mv: dict[str, Optional[Decimal]]
    fund_end_mv: dict[str, Optional[Decimal]]
    fund_end_shares: dict[str, Optional[Decimal]]
    fund_has_external_flow: dict[str, bool]
    platform_map: dict[str, Optional[str]]
    fund_map: dict[str, Fund]
    nav_observation_dates: set[date]
    total_pnl: Optional[Decimal]
    trading_days: int


class AnalysisService:
    def __init__(self, db: Session):
        self.db = db

    def get_periods(self) -> list[PeriodItem]:
        """Get all import periods (consecutive import pairs)."""
        records = self.db.execute(
            select(ImportRecord)
            .where(ImportRecord.status == "success")
            .order_by(ImportRecord.created_at.asc())
        ).scalars().all()

        if len(records) < 2:
            # 无导入记录(手填持仓)时: 用持仓 + 净值历史范围生成一个可分析期间
            return self._periods_no_import()

        periods = []
        for i in range(len(records) - 1):
            r_start = records[i]
            r_end = records[i + 1]
            start_date = r_start.data_date or r_start.created_at.date()
            end_date = r_end.data_date or r_end.created_at.date()

            # Calculate total PnL for this period
            total_pnl = self.db.execute(
                select(func.sum(HoldingDailyPnL.daily_pnl))
                .where(
                    HoldingDailyPnL.pnl_date > start_date,
                    HoldingDailyPnL.pnl_date <= end_date,
                )
            ).scalar()

            trading_days = self.db.execute(
                select(func.count(func.distinct(HoldingDailyPnL.pnl_date)))
                .where(
                    HoldingDailyPnL.pnl_date > start_date,
                    HoldingDailyPnL.pnl_date <= end_date,
                )
            ).scalar() or 0

            periods.append(PeriodItem(
                start_date=start_date,
                end_date=end_date,
                start_import_id=r_start.id,
                end_import_id=r_end.id,
                start_label=f"#{r_start.id} ({start_date})",
                end_label=f"#{r_end.id} ({end_date})",
                total_pnl=total_pnl,
                trading_days=trading_days,
            ))

        return periods

    def _periods_no_import(self) -> list[PeriodItem]:
        """无导入记录(手填持仓)时: 用持仓基金的净值历史范围生成单个分析期间。

        期间 = 从最早净值日期 到 最近净值日期, 让用户一路看到盈亏曲线。
        """
        holdings = self.db.execute(
            select(FundHolding.fund_code).distinct()
        ).scalars().all()
        if not holdings:
            return []

        date_row = self.db.execute(
            select(
                func.min(FundNavHistory.nav_date).label("mn"),
                func.max(FundNavHistory.nav_date).label("mx"),
            ).where(FundNavHistory.fund_code.in_(holdings))
        ).one()
        first_date, last_date = date_row.mn, date_row.mx
        if not first_date or not last_date:
            return []

        # 默认看近一年: 起点取 (最近净值日-1年) 与最早净值日的较晚者, 避免跨度过长
        from datetime import timedelta
        lookback_start = last_date - timedelta(days=365)
        if first_date > lookback_start:
            lookback_start = first_date
        first_date = lookback_start

        # 期间总盈亏与交易日数由净值现算
        total_pnl, trading_days = self._calc_pnl_range_no_import(
            holdings, first_date, last_date
        )

        return [
            PeriodItem(
                start_date=first_date,
                end_date=last_date,
                start_import_id=0,
                end_import_id=0,
                start_label=f"开始 ({first_date})",
                end_label=f"至今 ({last_date})",
                total_pnl=total_pnl,
                trading_days=trading_days,
            )
        ]

    def _calc_pnl_range_no_import(
        self, fund_codes: list[str], start_date: date, end_date: date
    ) -> tuple[Optional[Decimal], int]:
        """无导入时，返回共享历史核心计算出的期间盈亏与交易日数。"""
        result = self._build_no_snapshot_result(fund_codes, start_date, end_date)
        return result.total_pnl, result.trading_days
    def get_period_detail(
        self, start_date: date, end_date: date
    ) -> list[DailyPnLPoint]:
        """Get daily PnL points for a period."""
        rows = self.db.execute(
            select(
                HoldingDailyPnL.pnl_date,
                func.sum(HoldingDailyPnL.daily_pnl).label("total_pnl"),
                func.sum(HoldingDailyPnL.market_value).label("total_mv"),
            )
            .where(
                HoldingDailyPnL.pnl_date > start_date,
                HoldingDailyPnL.pnl_date <= end_date,
            )
            .group_by(HoldingDailyPnL.pnl_date)
            .order_by(HoldingDailyPnL.pnl_date)
        ).all()

        if rows:
            return [
                DailyPnLPoint(
                    pnl_date=r.pnl_date,
                    total_pnl=r.total_pnl,
                    total_mv=r.total_mv,
                )
                for r in rows
            ]

        # 无每日盈亏快照(手填持仓)时: 用持仓份额×净值现算每日盈亏
        return self._period_detail_no_import(start_date, end_date)

    def get_fund_pnl(
        self, start_date: date, end_date: date
    ) -> list[FundPnLSummary]:
        """Get per-fund PnL summary for a period."""
        # 无每日盈亏快照(手填持仓)时: 用持仓份额×净值现算单基金盈亏
        has_snapshot = self.db.execute(
            select(func.count()).select_from(HoldingDailyPnL).where(
                HoldingDailyPnL.pnl_date > start_date,
                HoldingDailyPnL.pnl_date <= end_date,
            )
        ).scalar()
        if not has_snapshot:
            return self._fund_pnl_no_import(start_date, end_date)

        # Aggregate daily PnL by fund_code
        rows = self.db.execute(
            select(
                HoldingDailyPnL.fund_code,
                func.sum(HoldingDailyPnL.daily_pnl).label("period_pnl"),
            )
            .where(
                HoldingDailyPnL.pnl_date > start_date,
                HoldingDailyPnL.pnl_date <= end_date,
            )
            .group_by(HoldingDailyPnL.fund_code)
        ).all()

        pnl_map = {r.fund_code: r.period_pnl for r in rows}

        # Get start MV (first day in period) and end MV (last day in period)
        first_date = self.db.execute(
            select(func.min(HoldingDailyPnL.pnl_date))
            .where(
                HoldingDailyPnL.pnl_date > start_date,
                HoldingDailyPnL.pnl_date <= end_date,
            )
        ).scalar()

        last_date = self.db.execute(
            select(func.max(HoldingDailyPnL.pnl_date))
            .where(
                HoldingDailyPnL.pnl_date > start_date,
                HoldingDailyPnL.pnl_date <= end_date,
            )
        ).scalar()

        if not first_date or not last_date:
            return []

        # Start MV per fund
        start_mv_rows = self.db.execute(
            select(
                HoldingDailyPnL.fund_code,
                func.sum(HoldingDailyPnL.market_value).label("mv"),
                func.sum(HoldingDailyPnL.shares).label("shares"),
            )
            .where(HoldingDailyPnL.pnl_date == first_date)
            .group_by(HoldingDailyPnL.fund_code)
        ).all()
        start_mv_map = {r.fund_code: (r.mv, r.shares) for r in start_mv_rows}

        # End MV per fund
        end_mv_rows = self.db.execute(
            select(
                HoldingDailyPnL.fund_code,
                func.sum(HoldingDailyPnL.market_value).label("mv"),
            )
            .where(HoldingDailyPnL.pnl_date == last_date)
            .group_by(HoldingDailyPnL.fund_code)
        ).all()
        end_mv_map = {r.fund_code: r.mv for r in end_mv_rows}

        # Fund info
        all_codes = set(pnl_map.keys())
        funds = self.db.execute(
            select(Fund).where(Fund.fund_code.in_(all_codes))
        ).scalars().all()
        fund_map = {f.fund_code: f for f in funds}

        # Holding info for platform
        holdings = self.db.execute(
            select(FundHolding.fund_code, FundHolding.platform)
            .where(FundHolding.fund_code.in_(all_codes))
            .distinct()
        ).all()
        platform_map = {r.fund_code: r.platform for r in holdings}

        results = []
        for code, period_pnl in pnl_map.items():
            fund = fund_map.get(code)
            s_mv, s_shares = start_mv_map.get(code, (None, None))
            e_mv = end_mv_map.get(code)

            pnl_pct = None
            if s_mv and s_mv > 0 and period_pnl is not None:
                pnl_pct = period_pnl / s_mv * 100

            results.append(FundPnLSummary(
                fund_code=code,
                fund_name=fund.fund_name if fund else None,
                platform=platform_map.get(code),
                shares=s_shares,
                start_mv=s_mv,
                end_mv=e_mv,
                period_pnl=period_pnl,
                period_pnl_pct=pnl_pct,
            ))

        # Sort by period_pnl desc
        results.sort(key=lambda x: x.period_pnl or Decimal("0"), reverse=True)
        return results

    # ------------------------------------------------------------------
    # 无快照回退支持：历史份额、净值和资金流统一在此处计算。
    # ------------------------------------------------------------------

    # 将数据库数值统一转换为 Decimal，避免浮点数参与金额计算。
    @staticmethod
    def _as_decimal(value) -> Optional[Decimal]:
        """把数据库数值安全转换为 Decimal。"""
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    # 按持仓事件和 legacy 规则还原某个持仓在目标日的份额。
    def _shares_on_date(
        self,
        holding: FundHolding,
        events: list[HoldingChange],
        target_date: date,
    ) -> tuple[Optional[Decimal], bool]:
        """返回目标日份额及是否因来源不足而不可确定。"""
        applicable = [
            event for event in events
            if event.business_date is not None and event.business_date <= target_date
        ]
        if events:
            if not applicable:
                return Decimal("0"), False
            event = applicable[-1]
            if event.shares_after is None:
                if event.change_type == "clear":
                    return Decimal("0"), False
                return None, True
            return self._as_decimal(event.shares_after), False

        if holding.source_type == "legacy":
            if holding.share_date is None or holding.share_date > target_date:
                return Decimal("0"), False
            if holding.status == 1 and holding.shares is not None:
                return self._as_decimal(holding.shares), False
            return None, True

        if holding.status == 0:
            return Decimal("0"), False
        return None, True

    # 在不晚于目标日的历史净值中取最近一条。
    @staticmethod
    def _latest_nav(
        navs: list[tuple[date, Decimal]], target_date: date
    ) -> Optional[Decimal]:
        """返回目标日可用的最近历史净值。"""
        latest = None
        for nav_date, unit_nav in navs:
            if nav_date > target_date:
                break
            latest = unit_nav
        return latest

    # 构建三个无快照回退共同消费的完整历史计算结果。
    def _build_no_snapshot_result(
        self, fund_codes: list[str], start_date: date, end_date: date
    ) -> _NoSnapshotResult:
        """按持仓事件、历史净值和资金流计算无快照期间结果。"""
        zero = Decimal("0")
        requested_codes = {code for code in fund_codes if code}
        empty = _NoSnapshotResult(
            dates=[],
            fund_codes=[],
            fund_days={},
            total_market_value={},
            total_daily_pnl={},
            fund_period_pnl={},
            fund_start_mv={},
            fund_end_mv={},
            fund_end_shares={},
            fund_has_external_flow={},
            platform_map={},
            fund_map={},
            nav_observation_dates=set(),
            total_pnl=None,
            trading_days=0,
        )
        if not requested_codes or end_date <= start_date:
            return empty

        holdings = [
            holding
            for holding in self.db.execute(select(FundHolding)).scalars().all()
            if holding.fund_code in requested_codes
        ]
        if not holdings:
            return empty

        holding_ids = [holding.id for holding in holdings if holding.id is not None]
        if holding_ids:
            changes = self.db.execute(
                select(HoldingChange)
                .where(
                    HoldingChange.holding_id.in_(holding_ids),
                    HoldingChange.business_date <= end_date,
                )
                .order_by(
                    HoldingChange.holding_id.asc(),
                    HoldingChange.business_date.asc(),
                    HoldingChange.id.asc(),
                )
            ).scalars().all()
        else:
            changes = []

        events_by_holding: dict[int, list[HoldingChange]] = defaultdict(list)
        for change in changes:
            if change.holding_id is not None:
                events_by_holding[change.holding_id].append(change)

        all_codes = {holding.fund_code for holding in holdings}
        money_codes = set(self.db.execute(
            select(Fund.fund_code).where(
                Fund.fund_code.in_(all_codes), Fund.fund_type == "货币型"
            )
        ).scalars().all())
        invest_codes = sorted(all_codes - money_codes)
        if not invest_codes:
            return empty

        nav_rows = self.db.execute(
            select(
                FundNavHistory.fund_code,
                FundNavHistory.nav_date,
                FundNavHistory.unit_nav,
            )
            .where(
                FundNavHistory.fund_code.in_(invest_codes),
                FundNavHistory.nav_date <= end_date,
            )
            .order_by(
                FundNavHistory.fund_code.asc(),
                FundNavHistory.nav_date.asc(),
            )
        ).all()
        nav_by_code: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
        nav_observation_dates: set[date] = set()
        for code, nav_date, unit_nav in nav_rows:
            nav = self._as_decimal(unit_nav)
            if nav is not None:
                nav_by_code[code].append((nav_date, nav))
                if start_date < nav_date <= end_date:
                    nav_observation_dates.add(nav_date)

        flow_by_code_date: dict[str, dict[date, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: zero)
        )
        invalid_flow_dates: dict[str, set[date]] = defaultdict(set)
        event_dates: set[date] = set()
        for change in changes:
            if change.fund_code not in invest_codes:
                continue
            if not change.business_date or not (
                start_date < change.business_date <= end_date
            ):
                continue
            event_dates.add(change.business_date)
            delta = self._as_decimal(change.shares_delta)
            nav_at_change = self._as_decimal(change.nav_at_change)
            if delta is None or nav_at_change is None:
                invalid_flow_dates[change.fund_code].add(change.business_date)
                continue
            flow_by_code_date[change.fund_code][change.business_date] += (
                delta * nav_at_change
            )

        dates = sorted({
            nav_date
            for code in invest_codes
            for nav_date, _ in nav_by_code.get(code, [])
            if start_date < nav_date <= end_date
        } | event_dates)
        if not dates:
            return empty

        legacy_baseline_dates: dict[str, set[date]] = defaultdict(set)
        for holding in holdings:
            if holding.fund_code not in invest_codes:
                continue
            if (
                not events_by_holding.get(holding.id)
                and holding.source_type == "legacy"
                and holding.status == 1
                and holding.share_date is not None
                and start_date < holding.share_date <= end_date
            ):
                legacy_baseline_dates[holding.fund_code].add(holding.share_date)

        fund_days: dict[str, dict[date, _NoSnapshotFundDay]] = {
            code: {} for code in invest_codes
        }
        all_valuation_dates = [start_date, *dates]
        for valuation_date in all_valuation_dates:
            shares_by_code: dict[str, Decimal] = defaultdict(lambda: zero)
            unknown_codes: set[str] = set()
            for holding in holdings:
                if holding.fund_code not in invest_codes:
                    continue
                holding_events = events_by_holding.get(holding.id, [])
                shares, unknown = self._shares_on_date(
                    holding, holding_events, valuation_date
                )
                if unknown or shares is None:
                    unknown_codes.add(holding.fund_code)
                    continue
                shares_by_code[holding.fund_code] += shares

            for code in invest_codes:
                shares = shares_by_code[code]
                nav = self._latest_nav(nav_by_code.get(code, []), valuation_date)
                if code in unknown_codes or (shares != zero and nav is None):
                    market_value = None
                elif shares == zero:
                    market_value = zero
                else:
                    market_value = shares * nav
                fund_days[code][valuation_date] = _NoSnapshotFundDay(
                    shares=shares,
                    market_value=market_value,
                )

        relevant_codes = [
            code for code in invest_codes
            if any(
                day.shares != zero or day.market_value is None
                for day in fund_days[code].values()
            )
        ]
        if not relevant_codes:
            return empty

        fund_period_pnl: dict[str, Optional[Decimal]] = {}
        fund_start_mv: dict[str, Optional[Decimal]] = {}
        fund_end_mv: dict[str, Optional[Decimal]] = {}
        fund_end_shares: dict[str, Optional[Decimal]] = {}
        fund_has_external_flow: dict[str, bool] = {}

        for code in relevant_codes:
            start_day = fund_days[code][start_date]
            previous_mv = start_day.market_value
            first_observed_mv = previous_mv
            period_values: list[Decimal] = []
            invalid_valuation = False
            invalid_flow = False
            has_flow = False

            for valuation_date in dates:
                day = fund_days[code][valuation_date]
                if day.market_value is None:
                    invalid_valuation = True
                    previous_mv = None
                    continue

                is_legacy_baseline = (
                    valuation_date in legacy_baseline_dates.get(code, set())
                    and day.shares != zero
                )
                if is_legacy_baseline:
                    day.daily_pnl = None
                    previous_mv = day.market_value
                    first_observed_mv = day.market_value
                    continue

                if previous_mv is None:
                    day.daily_pnl = None
                    previous_mv = day.market_value
                    if first_observed_mv is None:
                        first_observed_mv = day.market_value
                    continue

                if valuation_date in invalid_flow_dates.get(code, set()):
                    day.daily_pnl = None
                    invalid_flow = True
                    has_flow = True
                    previous_mv = day.market_value
                    continue

                flow = flow_by_code_date.get(code, {}).get(valuation_date, zero)
                if flow != zero:
                    has_flow = True
                day.daily_pnl = day.market_value - previous_mv - flow
                period_values.append(day.daily_pnl)
                previous_mv = day.market_value

            fund_period_pnl[code] = (
                None
                if invalid_valuation or invalid_flow or not period_values
                else sum(period_values, zero)
            )
            fund_start_mv[code] = first_observed_mv
            fund_end_mv[code] = fund_days[code][dates[-1]].market_value
            fund_end_shares[code] = fund_days[code][dates[-1]].shares
            fund_has_external_flow[code] = has_flow

        total_market_value: dict[date, Optional[Decimal]] = {}
        total_daily_pnl: dict[date, Optional[Decimal]] = {}
        for valuation_date in dates:
            day_values = [
                fund_days[code][valuation_date] for code in relevant_codes
            ]
            if any(day.market_value is None for day in day_values):
                total_market_value[valuation_date] = None
                total_daily_pnl[valuation_date] = None
                continue
            total_market_value[valuation_date] = sum(
                (day.market_value for day in day_values), zero
            )
            if any(day.daily_pnl is None for day in day_values):
                total_daily_pnl[valuation_date] = None
            else:
                total_daily_pnl[valuation_date] = sum(
                    (day.daily_pnl for day in day_values), zero
                )

        total_pnl = (
            None
            if any(fund_period_pnl[code] is None for code in relevant_codes)
            else sum((fund_period_pnl[code] for code in relevant_codes), zero)
        )
        trading_days = sum(
            valuation_date in nav_observation_dates
            and total_daily_pnl[valuation_date] is not None
            for valuation_date in dates
        )
        funds = self.db.execute(
            select(Fund).where(Fund.fund_code.in_(relevant_codes))
        ).scalars().all()
        fund_map = {fund.fund_code: fund for fund in funds}
        platforms: dict[str, set[str]] = defaultdict(set)
        for holding in holdings:
            if holding.fund_code in relevant_codes and holding.platform:
                platforms[holding.fund_code].add(holding.platform)
        platform_map = {
            code: "、".join(sorted(platforms[code])) if platforms[code] else None
            for code in relevant_codes
        }

        return _NoSnapshotResult(
            dates=dates,
            fund_codes=relevant_codes,
            fund_days={code: fund_days[code] for code in relevant_codes},
            total_market_value=total_market_value,
            total_daily_pnl=total_daily_pnl,
            fund_period_pnl=fund_period_pnl,
            fund_start_mv=fund_start_mv,
            fund_end_mv=fund_end_mv,
            fund_end_shares=fund_end_shares,
            fund_has_external_flow=fund_has_external_flow,
            platform_map=platform_map,
            fund_map=fund_map,
            nav_observation_dates=nav_observation_dates,
            total_pnl=total_pnl,
            trading_days=trading_days,
        )

    # 将共享核心转换为每日组合盈亏点。
    def _period_detail_no_import(
        self, start_date: date, end_date: date
    ) -> list[DailyPnLPoint]:
        """手填持仓时，按历史份额和历史净值生成每日盈亏曲线。"""
        holdings = self.db.execute(select(FundHolding)).scalars().all()
        codes = sorted({holding.fund_code for holding in holdings})
        result = self._build_no_snapshot_result(codes, start_date, end_date)
        return [
            DailyPnLPoint(
                pnl_date=valuation_date,
                total_pnl=result.total_daily_pnl[valuation_date],
                total_mv=result.total_market_value[valuation_date],
            )
            for valuation_date in result.dates
        ]

    # 将共享核心转换为各基金期间盈亏摘要。
    def _fund_pnl_no_import(
        self, start_date: date, end_date: date
    ) -> list[FundPnLSummary]:
        """手填持仓时，按历史份额和资金流生成单基金摘要。"""
        holdings = self.db.execute(select(FundHolding)).scalars().all()
        codes = sorted({holding.fund_code for holding in holdings})
        result = self._build_no_snapshot_result(codes, start_date, end_date)
        summaries: list[FundPnLSummary] = []
        for code in result.fund_codes:
            period_pnl = result.fund_period_pnl[code]
            start_mv = result.fund_start_mv[code]
            period_pnl_pct = None
            if (
                period_pnl is not None
                and start_mv is not None
                and start_mv > 0
                and not result.fund_has_external_flow[code]
            ):
                period_pnl_pct = period_pnl / start_mv * 100
            fund = result.fund_map.get(code)
            summaries.append(FundPnLSummary(
                fund_code=code,
                fund_name=fund.fund_name if fund else None,
                platform=result.platform_map.get(code),
                shares=result.fund_end_shares[code],
                start_mv=start_mv,
                end_mv=result.fund_end_mv[code],
                period_pnl=period_pnl,
                period_pnl_pct=period_pnl_pct,
            ))
        summaries.sort(key=lambda item: item.period_pnl or Decimal("0"), reverse=True)
        return summaries
