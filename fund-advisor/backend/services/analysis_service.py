"""Analysis service - period PnL analysis between imports."""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.holding_daily_pnl import HoldingDailyPnL
from backend.models.import_record import ImportRecord
from backend.models.nav_history import FundNavHistory
from backend.schemas.holding_daily_pnl import (
    PeriodItem,
    FundPnLSummary,
    DailyPnLPoint,
)


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
            select(FundHolding.fund_code).where(FundHolding.status != 0).distinct()
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
        """无导入时: 用当前持仓份额×净值算一段区间内的总盈亏与交易日数。"""
        from collections import defaultdict
        from decimal import Decimal as D
        from backend.models.holding import FundHolding

        shares_map: dict[str, D] = defaultdict(lambda: D("0"))
        hrows = self.db.execute(
            select(FundHolding.fund_code, FundHolding.shares)
            .where(FundHolding.status != 0)
        ).all()
        for code, sh in hrows:
            if sh:
                shares_map.setdefault(code, D("0"))
                shares_map[code] += sh

        # 每只基金在区间内的净值序列
        nav_rows = self.db.execute(
            select(FundNavHistory.fund_code, FundNavHistory.nav_date, FundNavHistory.unit_nav)
            .where(
                FundNavHistory.fund_code.in_(fund_codes),
                FundNavHistory.nav_date >= start_date,
                FundNavHistory.nav_date <= end_date,
            )
            .order_by(FundNavHistory.nav_date.asc())
        ).all()

        by_date: dict[date, dict[str, D]] = defaultdict(dict)
        for code, d, nav in nav_rows:
            by_date[d][code] = nav

        dates = sorted(by_date.keys())
        total_pnl = D("0")
        prev_mv: dict[str, D] = {}
        trading_days = 0
        for d in dates:
            day_mv = D("0")
            for code, nav in by_date[d].items():
                if code in shares_map:
                    day_mv += shares_map[code] * nav
            if prev_mv:
                total_pnl += day_mv - sum(prev_mv.values())
            trading_days += 1
            prev_mv = {k: by_date[d].get(k, D("0")) * shares_map.get(k, D("0")) for k in by_date[d]}

        return (total_pnl, trading_days)
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
    # 无导入(手填持仓)支持: 直接用持仓份额 × 历史净值现算
    # ------------------------------------------------------------------
    def _load_effective_shares(self) -> dict[str, Decimal]:
        """当前所有持仓份额聚合到 fund_code。"""
        from collections import defaultdict
        rows = self.db.execute(
            select(FundHolding.fund_code, FundHolding.shares)
            .where(FundHolding.status != 0)
        ).all()
        m: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for code, sh in rows:
            if sh:
                m[code] += sh
        return dict(m)

    def _period_detail_no_import(
        self, start_date: date, end_date: date
    ) -> list[DailyPnLPoint]:
        """手填持仓时, 按日现算组合市值与盈亏曲线。"""
        from collections import defaultdict
        from decimal import Decimal as D
        from backend.models.fund import Fund as _Fund

        shares = self._load_effective_shares()
        codes = list(shares.keys())
        if not codes:
            return []

        money_codes = self.db.execute(
            select(_Fund.fund_code).where(
                _Fund.fund_code.in_(codes), _Fund.fund_type == "货币型"
            )
        ).scalars().all()
        money_set = set(money_codes)
        invest_codes = [c for c in codes if c not in money_set]
        if not invest_codes:
            return []

        nav_rows = self.db.execute(
            select(FundNavHistory.fund_code, FundNavHistory.nav_date, FundNavHistory.unit_nav)
            .where(
                FundNavHistory.fund_code.in_(invest_codes),
                FundNavHistory.nav_date > start_date,
                FundNavHistory.nav_date <= end_date,
            )
            .order_by(FundNavHistory.nav_date.asc())
        ).all()
        if not nav_rows:
            return []

        by_date: dict[date, dict[str, Decimal]] = defaultdict(dict)
        for code, d, nav in nav_rows:
            by_date[d][code] = nav

        dates = sorted(by_date.keys())
        daily_mv: dict[date, Decimal] = {}
        for d in dates:
            daily_mv[d] = sum(
                (shares[c] * by_date[d][c] for c in by_date[d] if c in shares),
                D("0"),
            )

        points: list[DailyPnLPoint] = []
        prev = None
        for d in dates:
            mv = daily_mv[d]
            pnl = (mv - prev) if prev is not None else D("0")
            points.append(DailyPnLPoint(pnl_date=d, total_pnl=pnl, total_mv=mv))
            prev = mv
        return points

    def _fund_pnl_no_import(
        self, start_date: date, end_date: date
    ) -> list[FundPnLSummary]:
        """手填持仓时, 按基金现算期间盈亏。"""
        from decimal import Decimal as D
        from backend.models.fund import Fund as _Fund
        from collections import defaultdict

        shares = self._load_effective_shares()
        codes = list(shares.keys())
        if not codes:
            return []

        nav_rows = self.db.execute(
            select(FundNavHistory.fund_code, FundNavHistory.nav_date, FundNavHistory.unit_nav)
            .where(
                FundNavHistory.fund_code.in_(codes),
                FundNavHistory.nav_date > start_date,
                FundNavHistory.nav_date <= end_date,
            )
            .order_by(FundNavHistory.nav_date.asc())
        ).all()
        per_fund: dict[str, dict[date, Decimal]] = defaultdict(dict)
        for code, d, nav in nav_rows:
            per_fund[code][d] = nav

        funds = self.db.execute(
            select(_Fund).where(_Fund.fund_code.in_(codes))
        ).scalars().all()
        fund_map = {f.fund_code: f for f in funds}
        holdings = self.db.execute(
            select(FundHolding.fund_code, FundHolding.platform)
            .where(FundHolding.fund_code.in_(codes)).distinct()
        ).all()
        platform_map = {r.fund_code: r.platform for r in holdings}

        results: list[FundPnLSummary] = []
        for code in codes:
            navs = per_fund.get(code)
            if not navs:
                continue
            dates = sorted(navs.keys())
            fd, ld = dates[0], dates[-1]
            nav0, nav1 = navs[fd], navs[ld]
            sh = shares[code]
            start_mv = sh * nav0
            end_mv = sh * nav1
            period_pnl = end_mv - start_mv
            pnl_pct = (period_pnl / start_mv * 100) if start_mv else None
            f = fund_map.get(code)
            results.append(FundPnLSummary(
                fund_code=code,
                fund_name=f.fund_name if f else None,
                platform=platform_map.get(code),
                shares=sh,
                start_mv=start_mv,
                end_mv=end_mv,
                period_pnl=period_pnl,
                period_pnl_pct=pnl_pct,
            ))
        results.sort(key=lambda x: x.period_pnl or D("0"), reverse=True)
        return results
