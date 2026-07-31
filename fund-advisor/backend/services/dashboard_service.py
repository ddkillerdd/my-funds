"""Dashboard service - aggregated portfolio data for dashboard."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func, distinct
from sqlalchemy.orm import Session

from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.portfolio_snapshot import PortfolioSnapshot
from backend.schemas.dashboard import (
    DashboardSummary,
    PlatformDistribution,
    DailyPnLPoint,
    TopHolding,
)


ZERO = Decimal("0")


class DashboardService:
    def __init__(self, db: Session):
        self.db = db

    def _get_money_fund_codes(self) -> set[str]:
        """获取货币基金代码集合。"""
        rows = self.db.execute(
            select(Fund.fund_code).where(Fund.fund_type == "货币型")
        ).scalars().all()
        return set(rows)

    def get_summary(self) -> DashboardSummary:
        """Get portfolio summary with money fund and decimal fixes."""
        money_fund_codes = self._get_money_fund_codes()

        rows = self.db.execute(
            select(FundHolding, Fund)
            .outerjoin(Fund, FundHolding.fund_code == Fund.fund_code)
            .where(FundHolding.status == 1)
        ).all()

        total_mv = ZERO
        daily_pnl = ZERO
        fund_codes = set()
        platforms = set()

        for holding, fund in rows:
            shares = holding.shares or ZERO

            if holding.fund_code in money_fund_codes:
                # 货币基金：市值 = 份额（每份1元）
                mv = shares
                # 日盈亏 = 份额 * 最新万份收益 / 10000
                if fund and fund.nav_change_pct is not None:
                    # nav_change_pct 存的是 (万份收益 / 10000 * 100) 即日收益率%
                    # 反推万份收益 = nav_change_pct / 100 * 10000 = nav_change_pct * 100
                    # 日盈亏 = shares * (万份收益 / 10000) = shares * (nav_change_pct * 100 / 10000)
                    #        = shares * nav_change_pct / 100
                    daily_pnl += shares * fund.nav_change_pct / Decimal("100")
            else:
                # 普通基金
                if fund and fund.latest_nav and shares:
                    mv = shares * fund.latest_nav
                else:
                    # 兜底：使用导入时的 market_value，确保是 Decimal
                    mv = ZERO
                    if holding.market_value is not None:
                        mv = Decimal(str(holding.market_value))

                # 日盈亏反推：mv * nav_change_pct / (100 + nav_change_pct)
                if fund and fund.nav_change_pct is not None and mv:
                    pnl = mv * fund.nav_change_pct / (Decimal("100") + fund.nav_change_pct)
                    daily_pnl += pnl

            total_mv += mv
            fund_codes.add(holding.fund_code)
            platforms.add(holding.platform)

        daily_pnl_pct = None
        if total_mv > ZERO and daily_pnl != ZERO:
            daily_pnl_pct = (daily_pnl / total_mv * Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        latest_nav_date = self.db.execute(
            select(func.max(Fund.latest_nav_date))
        ).scalar()
        nav_update_time = str(latest_nav_date) if latest_nav_date else None

        return DashboardSummary(
            total_market_value=total_mv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            daily_pnl=daily_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            daily_pnl_pct=daily_pnl_pct,
            total_holdings=len(rows),
            total_funds=len(fund_codes),
            total_platforms=len(platforms),
            nav_update_time=nav_update_time,
        )

    def get_platform_distribution(self) -> list[PlatformDistribution]:
        """Get market value distribution by platform, with money fund handling."""
        money_fund_codes = self._get_money_fund_codes()

        rows = self.db.execute(
            select(FundHolding, Fund)
            .outerjoin(Fund, FundHolding.fund_code == Fund.fund_code)
            .where(FundHolding.status == 1)
        ).all()

        platform_map: dict[str, dict] = {}
        for holding, fund in rows:
            shares = holding.shares or ZERO

            if holding.fund_code in money_fund_codes:
                mv = shares
                pnl = ZERO
                if fund and fund.nav_change_pct is not None:
                    pnl = shares * fund.nav_change_pct / Decimal("100")
            else:
                if fund and fund.latest_nav and shares:
                    mv = shares * fund.latest_nav
                else:
                    mv = ZERO
                    if holding.market_value is not None:
                        mv = Decimal(str(holding.market_value))

                pnl = ZERO
                if fund and fund.nav_change_pct is not None and mv:
                    pnl = mv * fund.nav_change_pct / (Decimal("100") + fund.nav_change_pct)

            entry = platform_map.setdefault(holding.platform, {
                "market_value": ZERO,
                "count": 0,
                "daily_pnl": ZERO,
            })
            entry["market_value"] += mv
            entry["count"] += 1
            entry["daily_pnl"] += pnl

        total = sum(e["market_value"] for e in platform_map.values())
        results = []
        for platform, entry in platform_map.items():
            mv = entry["market_value"]
            pct = (mv / total * Decimal("100")) if total > ZERO else ZERO
            results.append(PlatformDistribution(
                platform=platform,
                market_value=mv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                count=entry["count"],
                percentage=round(pct, 2),
                daily_pnl=entry["daily_pnl"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            ))
        results.sort(key=lambda x: x.market_value, reverse=True)
        return results

    def get_daily_pnl(self, days: int = 30) -> list[DailyPnLPoint]:
        """Get daily PnL trend from snapshots."""
        cutoff = date.today() - timedelta(days=days)
        snapshots = self.db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.snapshot_date >= cutoff)
            .order_by(PortfolioSnapshot.snapshot_date.asc())
        ).scalars().all()

        return [
            DailyPnLPoint(
                date=s.snapshot_date,
                total_market_value=s.total_market_value,
                daily_pnl=s.daily_pnl,
                daily_pnl_pct=s.daily_pnl_pct,
                portfolio_nav=s.portfolio_nav,
                cumulative_return_pct=(s.portfolio_nav - 1) * 100 if s.portfolio_nav is not None else None,
            )
            for s in snapshots
        ]

    def get_top_holdings(self, limit: int = 10) -> list[TopHolding]:
        """Get top N holdings by aggregated market value."""
        money_fund_codes = self._get_money_fund_codes()

        rows = self.db.execute(
            select(
                FundHolding.fund_code,
                FundHolding.fund_name,
                func.sum(FundHolding.market_value).label("total_market_value"),
                func.sum(FundHolding.shares).label("total_shares"),
                func.count(distinct(FundHolding.platform)).label("platform_count"),
            )
            .where(FundHolding.status == 1)
            .group_by(FundHolding.fund_code, FundHolding.fund_name)
            .order_by(func.sum(FundHolding.market_value).desc())
            .limit(limit)
        ).all()

        results = []
        for r in rows:
            fund = self.db.execute(
                select(Fund).where(Fund.fund_code == r.fund_code)
            ).scalar_one_or_none()

            total_mv = ZERO
            if r.total_market_value is not None:
                total_mv = Decimal(str(r.total_market_value))
            # 货币基金：市值直接等于份额
            if fund and r.fund_code in money_fund_codes and r.total_shares:
                total_mv = r.total_shares

            results.append(TopHolding(
                fund_code=r.fund_code,
                fund_name=r.fund_name,
                total_market_value=total_mv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                total_shares=r.total_shares or ZERO,
                latest_nav=fund.latest_nav if fund else None,
                nav_change_pct=fund.nav_change_pct if fund else None,
                platform_count=r.platform_count or 1,
            ))

        return results
