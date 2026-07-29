"""Holding service - query, create, update, and manage fund holdings."""

from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, distinct, case
from sqlalchemy.orm import Session

from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.nav_history import FundNavHistory
from backend.schemas.holding import (
    HoldingResponse,
    HoldingsByPlatformResponse,
    HoldingCreate,
    HoldingDeleteResponse,
    SimpleImportRecord,
    SimpleImportResult,
)


ZERO = Decimal("0")


class HoldingService:
    def __init__(self, db: Session):
        self.db = db

    def _to_response(self, holding: FundHolding, fund: Optional[Fund] = None) -> HoldingResponse:
        """Convert ORM holding (+ optional fund) to response schema."""
        current_mv = None
        if fund and fund.latest_nav and holding.shares:
            current_mv = holding.shares * fund.latest_nav

        daily_pnl = None
        if current_mv and fund and fund.nav_change_pct:
            daily_pnl = current_mv * fund.nav_change_pct / (Decimal("100") + fund.nav_change_pct)

        total_pnl = None
        if current_mv and holding.cost_nav and holding.shares:
            cost_mv = holding.shares * holding.cost_nav
            total_pnl = current_mv - cost_mv

        return HoldingResponse(
            id=holding.id,
            fund_code=holding.fund_code,
            fund_name=holding.fund_name,
            share_type=holding.share_type,
            management_company=holding.management_company,
            platform=holding.platform,
            fund_account=holding.fund_account,
            trade_account=holding.trade_account,
            shares=holding.shares,
            share_date=holding.share_date,
            nav_on_import=holding.nav_on_import,
            nav_date=holding.nav_date,
            cost_nav=holding.cost_nav,
            market_value=holding.market_value,
            currency=holding.currency,
            dividend_mode=holding.dividend_mode,
            status=holding.status,
            latest_nav=fund.latest_nav if fund else None,
            latest_nav_date=fund.latest_nav_date if fund else None,
            nav_change_pct=fund.nav_change_pct if fund else None,
            current_market_value=current_mv,
            daily_pnl=daily_pnl,
            total_pnl=total_pnl,
            created_at=holding.created_at,
            updated_at=holding.updated_at,
        )

    def create_holding(self, data: HoldingCreate) -> HoldingResponse:
        """Create a new manual holding entry."""
        # Ensure fund exists in funds table
        fund = self.db.execute(
            select(Fund).where(Fund.fund_code == data.fund_code)
        ).scalar_one_or_none()

        if not fund:
            fund = Fund(
                fund_code=data.fund_code,
                fund_name=data.fund_name,
                management_company=data.management_company,
            )
            self.db.add(fund)
            self.db.flush()

        fund_account = data.fund_account or f"MANUAL_{data.fund_code}"
        trade_account = data.trade_account or fund_account

        holding = FundHolding(
            fund_code=data.fund_code,
            fund_name=data.fund_name,
            share_type=data.share_type or "前收费",
            management_company=data.management_company,
            platform=data.platform,
            fund_account=fund_account,
            trade_account=trade_account,
            shares=data.shares,
            share_date=data.share_date,
            nav_on_import=data.nav_on_import,
            cost_nav=data.cost_nav,
            market_value=data.market_value,
            currency=data.currency,
            dividend_mode=data.dividend_mode,
        )
        self.db.add(holding)
        self.db.commit()
        self.db.refresh(holding)

        return self._to_response(holding, fund)

    def delete_holding(self, holding_id: int) -> HoldingDeleteResponse:
        """Soft delete (set status=0) a holding."""
        holding = self.db.execute(
            select(FundHolding).where(FundHolding.id == holding_id)
        ).scalar_one_or_none()

        if not holding:
            raise ValueError(f"Holding {holding_id} not found")

        holding.status = 0
        self.db.commit()

        return HoldingDeleteResponse(
            id=holding.id,
            fund_code=holding.fund_code,
            fund_name=holding.fund_name,
        )

    def get_holdings(
        self,
        platform: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "market_value",
        sort_order: str = "desc",
    ) -> list[HoldingResponse]:
        """Get all active holdings with optional filters."""
        query = (
            select(FundHolding, Fund)
            .outerjoin(Fund, FundHolding.fund_code == Fund.fund_code)
            .where(FundHolding.status == 1)
        )

        if platform:
            query = query.where(FundHolding.platform == platform)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                (FundHolding.fund_code.like(search_term))
                | (FundHolding.fund_name.like(search_term))
            )

        sort_col = self._get_sort_column(sort_by)
        if sort_order == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(
                case((sort_col.is_(None), 1), else_=0),
                sort_col.desc(),
            )

        rows = self.db.execute(query).all()
        return [self._to_response(holding, fund) for holding, fund in rows]

    def get_holdings_by_platform(self) -> list[HoldingsByPlatformResponse]:
        """Get holdings grouped by platform."""
        platforms = self.get_platforms()
        results = []

        for platform in platforms:
            holdings = self.get_holdings(platform=platform)
            total_mv = sum(
                h.current_market_value or h.market_value or ZERO
                for h in holdings
            )
            results.append(HoldingsByPlatformResponse(
                platform=platform,
                count=len(holdings),
                total_market_value=total_mv,
                holdings=holdings,
            ))

        results.sort(key=lambda x: x.total_market_value or 0, reverse=True)
        return results

    def get_platforms(self) -> list[str]:
        """Get all distinct platform names from active holdings."""
        result = self.db.execute(
            select(distinct(FundHolding.platform))
            .where(FundHolding.status == 1)
            .order_by(FundHolding.platform)
        ).scalars().all()
        return list(result)

    def update_cost(self, holding_id: int, cost_nav: Decimal) -> HoldingResponse:
        """Update cost_nav for a holding."""
        holding = self.db.execute(
            select(FundHolding).where(FundHolding.id == holding_id)
        ).scalar_one_or_none()

        if not holding:
            raise ValueError(f"Holding {holding_id} not found")

        holding.cost_nav = cost_nav
        self.db.commit()
        self.db.refresh(holding)

        fund = self.db.execute(
            select(Fund).where(Fund.fund_code == holding.fund_code)
        ).scalar_one_or_none()

        return self._to_response(holding, fund)

    def _get_sort_column(self, sort_by: str):
        """Map sort field name to SQLAlchemy column."""
        mapping = {
            "market_value": FundHolding.market_value,
            "shares": FundHolding.shares,
            "fund_code": FundHolding.fund_code,
            "fund_name": FundHolding.fund_name,
            "platform": FundHolding.platform,
        }
        return mapping.get(sort_by, FundHolding.market_value)

    # ---------- Simple Import (RFC-002) ----------

    def simple_import(self, records: list[SimpleImportRecord]) -> SimpleImportResult:
        """Import holdings with just fund_code + market_value.

        Auto-resolves fund_name from funds table.
        Auto-calculates shares from market_value / latest_nav.
        Creates fund entry if not exists (NAV backfilled later).
        """
        result = SimpleImportResult()
        result.total = len(records)

        for rec in records:
            try:
                holding = self._simple_import_one(rec)
                result.success += 1
                result.details.append(holding)
            except Exception as e:
                result.errors.append({
                    "fund_code": rec.fund_code,
                    "message": str(e),
                })

        return result

    def _simple_import_one(self, rec: SimpleImportRecord) -> HoldingResponse:
        """Import a single holding from fund_code + market_value."""
        # Resolve fund
        fund = self.db.execute(
            select(Fund).where(Fund.fund_code == rec.fund_code)
        ).scalar_one_or_none()

        if fund:
            fund_name = fund.fund_name
        else:
            # Create stub fund entry (name will be backfilled by NAV refresh)
            fund = Fund(fund_code=rec.fund_code, fund_name=f"基金{rec.fund_code}")
            self.db.add(fund)
            self.db.flush()
            fund_name = fund.fund_name

        # Try to get latest NAV
        nav = fund.latest_nav
        nav_date = fund.latest_nav_date

        # Try nav_history if fund table doesn't have it
        if nav is None:
            latest_nav_row = self.db.execute(
                select(FundNavHistory)
                .where(FundNavHistory.fund_code == rec.fund_code)
                .order_by(FundNavHistory.nav_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_nav_row:
                nav = latest_nav_row.unit_nav
                nav_date = latest_nav_row.nav_date

        # Calculate shares (or mark as pending)
        if nav and nav > 0:
            shares = rec.market_value / nav
        else:
            shares = ZERO  # No NAV yet; backfill later

        fund_account = f"ALIPAY_{rec.fund_code}"
        existing = self.db.execute(
            select(FundHolding).where(
                FundHolding.fund_code == rec.fund_code,
                FundHolding.platform == rec.platform,
                FundHolding.fund_account == fund_account,
                FundHolding.status == 1,
            )
        ).scalar_one_or_none()

        if existing:
            # Update shares and market_value on existing holding
            existing.shares = shares
            existing.share_date = rec.share_date
            existing.market_value = rec.market_value
            if nav:
                existing.nav_on_import = nav
                existing.nav_date = nav_date
                existing.cost_nav = existing.cost_nav or nav
            existing.last_import_id = None
            self.db.flush()
            self.db.refresh(existing)
            return self._to_response(existing, fund)

        # Create new holding
        holding = FundHolding(
            fund_code=rec.fund_code,
            fund_name=fund_name,
            platform=rec.platform,
            fund_account=fund_account,
            trade_account=fund_account,
            shares=shares,
            share_date=rec.share_date,
            market_value=rec.market_value,
            nav_on_import=nav,
            nav_date=nav_date,
            cost_nav=nav,
            status=1,
        )
        self.db.add(holding)
        self.db.flush()
        self.db.refresh(holding)
        return self._to_response(holding, fund)
