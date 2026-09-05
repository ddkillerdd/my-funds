"""Holding service - query, create, update, and manage fund holdings."""

from datetime import date
from decimal import Decimal
from typing import Optional
import logging

from sqlalchemy import select, func, distinct, case
from sqlalchemy.orm import Session

from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.nav_history import FundNavHistory
from backend.models.holding_change import HoldingChange
from backend.services.nav_fetcher import fetch_fund_info
from backend.schemas.holding_change import HoldingChangeResponse as OperationChangeResponse
from backend.schemas.holding import (
    HoldingResponse,
    HoldingsByPlatformResponse,
    HoldingCreate,
    HoldingDeleteResponse,
    SimpleImportRecord,
    SimpleImportResult,
    HoldingChangeRequest,
    HoldingChangeResponse,
    SimpleImportPreviewRequest,
    SimpleImportPreviewResponse,
)

logger = logging.getLogger(__name__)


ZERO = Decimal("0")


def build_holding_change(
    *, holding_id: int, fund_code: str, fund_name: str | None,
    platform: str | None, change_type: str, shares_before: Decimal,
    shares_after: Decimal, shares_delta: Decimal, nav_at_change: Decimal | None,
    mv_before: Decimal, mv_after: Decimal, business_date: date,
    source_type: str, import_id: int | None = None,
) -> HoldingChange:
    """构造统一格式的持仓变动事件。"""
    return HoldingChange(
        import_id=import_id,
        holding_id=holding_id,
        fund_code=fund_code,
        fund_name=fund_name,
        platform=platform,
        change_type=change_type,
        shares_before=shares_before,
        shares_after=shares_after,
        shares_delta=shares_delta,
        nav_at_change=nav_at_change,
        mv_before=mv_before,
        mv_after=mv_after,
        business_date=business_date,
        source_type=source_type,
    )


class HoldingService:
    def __init__(self, db: Session):
        self.db = db

    def _to_response(self, holding: FundHolding, fund: Optional[Fund] = None) -> HoldingResponse:
        """Convert ORM holding (+ optional fund) to response schema."""
        response_fund_name = fund.fund_name if fund else holding.fund_name
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
            fund_name=response_fund_name,
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
            source_type=getattr(holding, "source_type", "legacy"),
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

        try:
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
                fund_code=data.fund_code, fund_name=data.fund_name,
                share_type=data.share_type or "前收费",
                management_company=data.management_company, platform=data.platform,
                fund_account=fund_account, trade_account=trade_account,
                shares=data.shares, share_date=data.share_date,
                nav_on_import=data.nav_on_import, cost_nav=data.cost_nav,
                market_value=data.market_value, currency=data.currency,
                dividend_mode=data.dividend_mode, source_type="manual",
            )
            self.db.add(holding)
            self.db.flush()
            self.db.add(build_holding_change(
                holding_id=holding.id, fund_code=holding.fund_code,
                fund_name=fund.fund_name, platform=holding.platform,
                change_type="new", shares_before=ZERO, shares_after=holding.shares,
                shares_delta=holding.shares, nav_at_change=holding.nav_on_import,
                mv_before=ZERO, mv_after=holding.market_value or ZERO,
                business_date=data.share_date, source_type="manual",
            ))
            self.db.commit()
            self.db.refresh(holding)
        except Exception:
            self.db.rollback()
            raise

        return self._to_response(holding, fund)

    def delete_holding(self, holding_id: int) -> HoldingDeleteResponse:
        """Soft delete (set status=0) a holding."""
        holding = self.db.execute(
            select(FundHolding).where(FundHolding.id == holding_id)
        ).scalar_one_or_none()

        if not holding:
            raise ValueError(f"Holding {holding_id} not found")
        if holding.status != 1 or Decimal(holding.shares or 0) <= 0:
            raise ValueError(f"Holding {holding_id} is already cleared")

        old_shares = Decimal(holding.shares or 0)
        old_market_value = Decimal(holding.market_value or 0)
        holding.status = 0
        holding.shares = ZERO
        holding.market_value = ZERO
        try:
            self.db.add(build_holding_change(
                holding_id=holding.id, fund_code=holding.fund_code,
                fund_name=holding.fund_name, platform=holding.platform,
                change_type="clear", shares_before=old_shares, shares_after=ZERO,
                shares_delta=-old_shares, nav_at_change=holding.nav_on_import,
                mv_before=old_market_value, mv_after=ZERO,
                business_date=date.today(), source_type="manual",
            ))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

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

    # ---------- RFC-011: Holding Change (add/reduce by RMB amount) ----------

    def record_change(self, holding_id: int, body: HoldingChangeRequest) -> HoldingChangeResponse:
        """Record an add (increase) or reduce (decrease) operation by RMB amount.

        Add:
            shares_delta = amount / nav
            new_shares = old + delta
            new cost_nav = (old_total_cost + amount) / new_shares   # recompute avg cost
        Reduce:
            shares_delta = amount / nav
            new_shares = old - delta
            cost_nav unchanged; if new_shares <= 0 -> clear (status=0)

        Always writes a holding_changes record.
        """
        change_type = (body.change_type or "").strip().lower()
        if change_type not in ("increase", "decrease"):
            raise ValueError(f"Invalid change_type '{body.change_type}', must be increase|decrease")
        if not body.amount or body.amount <= 0:
            raise ValueError("amount must be > 0")

        holding = self.db.execute(
            select(FundHolding).where(FundHolding.id == holding_id)
        ).scalar_one_or_none()
        if not holding:
            raise ValueError(f"Holding {holding_id} not found")
        if holding.status != 1:
            raise ValueError(f"Holding {holding_id} is not active (status={holding.status})")

        # Resolve operation nav: cost_nav_input > latest net asset value > fund.latest_nav
        nav = body.cost_nav_input
        if not nav or nav <= 0:
            fund = self.db.execute(
                select(Fund).where(Fund.fund_code == holding.fund_code)
            ).scalar_one_or_none()
            nav = fund.latest_nav if fund and fund.latest_nav else None
        if not nav or nav <= 0:
            latest = self.db.execute(
                select(FundNavHistory)
                .where(FundNavHistory.fund_code == holding.fund_code)
                .order_by(FundNavHistory.nav_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest and latest.unit_nav:
                nav = latest.unit_nav
        if not nav or nav <= 0:
            raise ValueError(f"No NAV available to convert amount for {holding.fund_code}")

        nav = Decimal(nav)
        amount = Decimal(body.amount)
        shares_delta = (amount / nav).quantize(Decimal("0.0001"))

        old_shares = Decimal(holding.shares or 0)
        old_cost_nav = Decimal(holding.cost_nav or 0)
        old_market_value = Decimal(holding.market_value or 0)

        if change_type == "increase":
            new_shares = old_shares + shares_delta
            # Recompute average cost: (old_total_cost + amount) / new_shares
            old_total_cost = old_shares * old_cost_nav
            new_cost_nav = (old_total_cost + amount) / new_shares
            new_cost_nav = new_cost_nav.quantize(Decimal("0.0001"))
            new_market_value = (new_shares * nav).quantize(Decimal("0.0001"))
            record_type = "increase"
            final_status = 1
        else:  # decrease
            new_shares = old_shares - shares_delta
            record_type = "decrease"
            if new_shares <= 0:
                new_shares = Decimal("0")
                record_type = "clear"
                final_status = 0  # clear / soft-delete
            else:
                final_status = 1
            # cost_nav unchanged on reduce/clear
            new_market_value = (new_shares * nav).quantize(Decimal("0.0001"))

        try:
            holding.shares = new_shares
            holding.market_value = new_market_value
            holding.status = final_status
            # 手工变动接管持仓所有权，后续文件快照不得清理它。
            holding.source_type = "manual"
            holding.last_import_id = None
            if new_shares > 0:
                holding.nav_on_import = nav
                holding.cost_nav = new_cost_nav if change_type == "increase" else holding.cost_nav
            self.db.flush()

            # 手工变动不伪造 ImportRecord，使用空 import_id 和明确业务日期。
            signed_delta = new_shares - old_shares
            change = build_holding_change(
                holding_id=holding.id, fund_code=holding.fund_code,
                fund_name=holding.fund_name, platform=holding.platform,
                change_type=record_type, shares_before=old_shares,
                shares_after=new_shares, shares_delta=signed_delta,
                nav_at_change=nav, mv_before=old_market_value,
                mv_after=new_market_value,
                business_date=body.business_date or date.today(),
                source_type="manual",
            )
            self.db.add(change)
            self.db.commit()
            self.db.refresh(holding)
        except Exception:
            self.db.rollback()
            raise

        fund = self.db.execute(
            select(Fund).where(Fund.fund_code == holding.fund_code)
        ).scalar_one_or_none()

        return HoldingChangeResponse(
            holding=self._to_response(holding, fund),
            change={
                "id": change.id,
                "change_type": record_type,
                "shares_delta": str(signed_delta),
                "shares_before": str(old_shares),
                "shares_after": str(new_shares),
                "nav_at_change": str(nav),
                "amount": str(amount),
                "cost_nav_after": str(holding.cost_nav or 0),
            },
            message=("清仓" if record_type == "clear" else ("加仓" if record_type == "increase" else "减仓"))
            + "成功，下次分析将基于最新持仓",
        )


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
            # RFIC-015 导入校验: 脏数据不落库, 记入 errors
            error = self._validate_simple_record(rec)
            if error:
                result.errors.append({"fund_code": rec.fund_code, "platform": rec.platform, "message": error})
                continue
            try:
                holding = self._simple_import_one(rec)
                # 每条快捷导入独立提交，避免单条失败污染后续记录。
                self.db.commit()
                result.success += 1
                result.details.append(holding)
            except Exception as e:
                # 回滚当前记录的全部 flush，确保后续记录从干净事务开始。
                self.db.rollback()
                logger.error(f"Failed to import {rec.fund_code}: {e}")
                result.errors.append({
                    "fund_code": rec.fund_code,
                    "platform": rec.platform,
                    "message": str(e),
                })

        return result

    def _validate_simple_record(self, rec: SimpleImportRecord) -> Optional[str]:
        """RFC-015 导入校验。返回错误信息, 无错误返回 None。

        校验项:
          1. fund_code 必须 6 位纯数字(基金代码格式)
          2. market_value 必须 > 0 且为有限数
          3. platform 必须非空
        """
        code = (rec.fund_code or "").strip()
        if not code:
            return "基金代码不能为空"
        if not (code.isdigit() and len(code) == 6):
            return f"基金代码格式非法: {code!r}(应为6位数字)"

        mv = rec.market_value
        if mv is None:
            return "持有金额不能为空"
        if mv <= 0:
            return f"持有金额必须大于0, 收到 {mv}"
        try:
            float(mv)
        except (TypeError, ValueError):
            return f"持有金额非法: {mv!r}"

        platform = (rec.platform or "").strip()
        if not platform:
            return "销售平台不能为空"
        if not mv.is_finite():
            return "持有金额必须是有限数"
        return None

    def _resolve_simple_fund_data(self, record: SimpleImportRecord):
        """只读解析快捷导入共用的基金名称、净值和净值日期。"""
        code = (record.fund_code or "").strip()
        fund = self.db.execute(select(Fund).where(Fund.fund_code == code)).scalar_one_or_none()
        info = None
        if fund and not (self._is_placeholder_fund(fund) or not self._valid_nav(fund.latest_nav)):
            fund_name, nav, nav_date = fund.fund_name, fund.latest_nav, fund.latest_nav_date
        else:
            info = fetch_fund_info(code)
            if not info:
                raise ValueError(f"基金 {code} 信息获取失败，请稍后重试")
            fund_name, nav, nav_date = info.fund_name, info.latest_nav, info.latest_nav_date
        if not self._valid_nav(nav):
            latest = self.db.execute(
                select(FundNavHistory).where(FundNavHistory.fund_code == code)
                .order_by(FundNavHistory.nav_date.desc()).limit(1)
            ).scalar_one_or_none()
            if latest:
                nav, nav_date = latest.unit_nav, latest.nav_date
        if not self._valid_nav(nav):
            raise ValueError(f"基金 {code} 暂无可用净值，请稍后重试")
        return fund, info, fund_name, nav, nav_date

    def preview_simple_import(self, record: SimpleImportPreviewRequest) -> SimpleImportPreviewResponse:
        """只读解析快捷导入所需基金信息、净值和估算份额。"""
        code = (record.fund_code or "").strip()
        normalized = SimpleImportRecord(
            fund_code=code, market_value=record.market_value,
            platform=record.platform.strip(), share_date=record.share_date,
        )
        error = self._validate_simple_record(normalized)
        if error:
            raise ValueError(error)
        _, _, fund_name, nav, nav_date = self._resolve_simple_fund_data(normalized)
        return SimpleImportPreviewResponse(
            fund_code=code, platform=normalized.platform, share_date=normalized.share_date,
            fund_name=fund_name, latest_nav=nav, latest_nav_date=nav_date,
            estimated_shares=normalized.market_value / nav,
        )

    def get_operation_history(self, limit: int = 100) -> list[OperationChangeResponse]:
        """按业务日期和事件 id 倒序读取统一操作历史。"""
        bounded_limit = min(max(int(limit), 1), 100)
        rows = self.db.execute(
            select(HoldingChange)
            .order_by(HoldingChange.business_date.desc(), HoldingChange.id.desc())
            .limit(bounded_limit)
        ).scalars().all()
        return [OperationChangeResponse.model_validate(row) for row in rows]

    def _simple_import_one(self, rec: SimpleImportRecord) -> HoldingResponse:
        """Import a single holding from fund_code + market_value."""
        fund, info, fund_name, nav, nav_date = self._resolve_simple_fund_data(rec)
        if fund is None:
            fund = Fund(
                fund_code=rec.fund_code.strip(), fund_name=fund_name,
                latest_nav=nav, latest_nav_date=nav_date,
            )
            self.db.add(fund)
            self.db.flush()
        elif info is not None:
            fund.fund_name = fund_name
            fund.latest_nav = nav
            fund.latest_nav_date = nav_date
        shares = rec.market_value / nav

        # 快捷导入按平台和基金代码生成稳定身份，不把平台写死为支付宝。
        fund_account = f"{rec.platform}_{rec.fund_code}"
        existing = self.db.execute(
            select(FundHolding).where(
                FundHolding.fund_code == rec.fund_code,
                FundHolding.platform == rec.platform,
                FundHolding.fund_account == fund_account,
            )
        ).scalar_one_or_none()

        if existing:
            # Update shares and market_value on existing holding (reactivate if was soft-deleted)
            old_shares = Decimal(existing.shares or 0)
            old_market_value = Decimal(existing.market_value or 0)
            existing.shares = shares
            existing.share_date = rec.share_date
            existing.market_value = rec.market_value
            existing.status = 1
            if nav:
                existing.nav_on_import = nav
                existing.nav_date = nav_date
            existing.last_import_id = None
            existing.source_type = "quick"
            self.db.flush()
            if shares != old_shares:
                change_type = "increase" if shares > old_shares else "decrease"
                self.db.add(build_holding_change(
                    holding_id=existing.id, fund_code=existing.fund_code,
                    fund_name=fund.fund_name, platform=existing.platform,
                    change_type=change_type, shares_before=old_shares,
                    shares_after=shares, shares_delta=shares - old_shares,
                    nav_at_change=nav, mv_before=old_market_value,
                    mv_after=rec.market_value, business_date=rec.share_date,
                    source_type="quick",
                ))
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
            # 快捷导入没有成本价，不能用最新净值伪造成本。
            cost_nav=None,
            status=1,
            source_type="quick",
        )
        self.db.add(holding)
        self.db.flush()
        self.db.add(build_holding_change(
            holding_id=holding.id, fund_code=holding.fund_code,
            fund_name=fund.fund_name, platform=holding.platform,
            change_type="new", shares_before=ZERO, shares_after=shares,
            shares_delta=shares, nav_at_change=nav, mv_before=ZERO,
            mv_after=rec.market_value, business_date=rec.share_date,
            source_type="quick",
        ))
        return self._to_response(holding, fund)

    @staticmethod
    def _valid_nav(nav: Optional[Decimal]) -> bool:
        """判断净值是否为可用于份额换算的正数。"""
        return nav is not None and nav > 0

    @staticmethod
    def _is_placeholder_fund(fund: Fund) -> bool:
        """识别历史导入留下的基金名称占位值。"""
        name = (fund.fund_name or "").strip()
        return (
            not name
            or name == fund.fund_code
            or name == f"基金{fund.fund_code}"
            or name in {"未知基金", "待补全"}
        )
