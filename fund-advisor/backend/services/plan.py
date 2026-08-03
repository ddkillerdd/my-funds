"""PlanService - 投资计划编排 (RFC-018 ⑤⑥ 核心).

资金簿 + 分批 + 确认建仓 + 长期跟踪。

生命周期:
  create_plan(draft) -> generates tranches -> confirm(建仓, active) -> completed

分批次(且慢"100份"):
  unit = total_budget / 100  (每份金额概念分母)
  每批投入金额 = 本批预算 × dca倍率(0.6/1.0/1.3)
  默认按周/双周分 3-6 个月建完; 每批按配比权重分配到单只基金。

确认建仓:
  单只基金按 计划配比权重 × 本批金额 买入 -> 写 plan_holding(独立核算浮盈)
  同时写全局 holdings(每日顾问整体分析), 扣余额(used+/remaining-), tranche -> executed
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.models.portfolio_plan import PortfolioPlan
from backend.models.plan_tranche import PlanTranche
from backend.models.plan_holding import PlanHolding
from backend.models.fund_candidate import FundCandidate

logger = logging.getLogger(__name__)

# 分批参数
DEFAULT_BATCH_WINDOW_WEEKS = 16      # 默认 16 周(约4个月)建完
BATCH_INTERVAL_WEEKS = 2             # 默认双周一批
WINDOW_MULTIPLIER = {
    "now_entry": 1.3,                # 可买入 -> 多投
    "staged_entry": 1.0,             # 分批建仓 -> 标准
    "wait": 0.6,                     # 等待 -> 少投
    "avoid": 0.0,                    # 避免 -> 停投
}
DEFAULT_WINDOW = "staged_entry"


class PlanService:
    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────
    #  创建计划(draft): 预算 + 配比 + AI解读
    # ─────────────────────────────────────────
    def create_plan(
        self,
        total_budget: float,
        risk_profile: str = "balanced",
        name: str = "我的入场计划",
        target_allocation: Optional[Dict[str, float]] = None,
        ai_summary: Optional[str] = None,
    ) -> PortfolioPlan:
        if not target_allocation:
            raise ValueError("target_allocation 不能为空")
        if total_budget <= 0:
            raise ValueError("预算必须 > 0")

        plan = PortfolioPlan(
            name=name,
            total_budget=Decimal(str(total_budget)),
            used_amount=Decimal("0"),
            remaining=Decimal(str(total_budget)),
            risk_profile=risk_profile,
            status="draft",
            target_allocation={str(k): float(v) for k, v in target_allocation.items()},
            ai_summary=ai_summary,
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    # ─────────────────────────────────────────
    #  生成分批计划(draft 后调用, 写 plan_tranche)
    # ─────────────────────────────────────────
    def generate_tranches(
        self,
        plan_id: int,
        fund_windows: Optional[Dict[str, str]] = None,
        total_weeks: int = DEFAULT_BATCH_WINDOW_WEEKS,
        interval_weeks: int = BATCH_INTERVAL_WEEKS,
    ) -> List[dict]:
        """按周/双周生成分批批次。

        fund_windows: {fund_code: window} 每只基金择时档位(默认 staged_entry)。
        组合级倍率 = 各基金 window 倍率按配比权重加权。
        """
        plan = self.db.execute(
            select(PortfolioPlan).where(PortfolioPlan.id == plan_id)
        ).scalar_one_or_none()
        if not plan:
            raise ValueError(f"计划 {plan_id} 不存在")

        alloc = plan.target_allocation or {}
        if not alloc:
            raise ValueError("计划无配比")

        # 先清旧批次再生成
        self.db.execute(PlanTranche.__table__.delete().where(PlanTranche.plan_id == plan_id))

        # 组合级窗口: 按权重加权
        fund_windows = fund_windows or {}
        total_weeks = max(4, int(total_weeks))
        interval_weeks = max(1, int(interval_weeks))
        n_batches = max(2, total_weeks // interval_weeks)

        # 每只基金窗口 -> 倍率
        code_mult = {}
        for code, wgt in alloc.items():
            window = fund_windows.get(code, DEFAULT_WINDOW)
            code_mult[code] = WINDOW_MULTIPLIER.get(window, 1.0)

        # 组合级倍率 = 加权
        total_w = sum(alloc.values()) or 1.0
        composite_mult = sum(
            code_mult.get(code, 1.0) * (wgt / total_w) for code, wgt in alloc.items()
        )
        composite_window = _composite_window(fund_windows)

        unit = float(plan.total_budget) / 100.0
        budget_per_batch = float(plan.total_budget) / n_batches

        # 生成批次
        start_date = datetime.now().date()
        tranches = []
        for i in range(1, n_batches + 1):
            batch_amount = budget_per_batch * composite_mult
            # avoide 时停投(整批跳过金额记 0, 但保留批次标记)
            if composite_mult <= 0.001:
                batch_amount = 0.0
            batch_units = round(batch_amount / unit, 2) if unit > 0 else 0
            plan_date = start_date + timedelta(weeks=(i - 1) * interval_weeks)
            t = PlanTranche(
                plan_id=plan_id,
                tranche_no=i,
                units=Decimal(str(batch_units)),
                window=composite_window,
                dca_multiplier=Decimal(str(round(composite_mult, 2))),
                plan_date=plan_date,
                status="pending",
                amount=Decimal(str(round(batch_amount, 2))),
            )
            self.db.add(t)
            tranches.append(t)
        self.db.commit()
        for t in tranches:
            self.db.refresh(t)
        return [t.concise() for t in tranches]

    # ─────────────────────────────────────────
    #  确认建仓: 逐批执行(先做首批), 建持仓 + 扣余额
    # ─────────────────────────────────────────
    def confirm_entry(self, plan_id: int, execute_tranches: int = 1) -> dict:
        """确认入场并把前 execute_tranches 批落地为持仓。"""
        plan = self.db.execute(
            select(PortfolioPlan).where(PortfolioPlan.id == plan_id)
        ).scalar_one_or_none()
        if not plan:
            raise ValueError(f"计划 {plan_id} 不存在")
        if plan.status == "completed":
            raise ValueError("计划已完成")

        alloc = plan.target_allocation or {}
        if not alloc:
            raise ValueError("计划无配比")

        # 找待执行批次
        pending = self.db.execute(
            select(PlanTranche)
            .where(PlanTranche.plan_id == plan_id, PlanTranche.status == "pending")
            .order_by(PlanTranche.tranche_no.asc())
        ).scalars().all()
        if not pending:
            raise ValueError("没有待执行批次(计划可能已全部完成)")

        to_execute = pending[:execute_tranches]
        executed_txn = []
        total_spent = Decimal("0")

        from backend.services.import_service import ImportService

        for tr in to_execute:
            batch_amount = Decimal(str(tr.amount or 0))
            # 校验余额
            remaining = plan.remaining or Decimal("0")
            if batch_amount > remaining:
                batch_amount = remaining
            if batch_amount <= 0:
                tr.amount = Decimal("0")
                tr.status = "executed"
                tr.executed_at = datetime.utcnow()
                continue

            # 按配比权重分配到单只, 写 plan_holding + 全局 holdings
            spent_this = Decimal("0")
            for code, wgt_pct in alloc.items():
                fund_amount = batch_amount * Decimal(str(wgt_pct / 100.0))
                if fund_amount <= 0:
                    continue
                nav = self._latest_nav(code)
                if nav and nav > 0:
                    shares = fund_amount / Decimal(str(nav))
                    self._upsert_plan_holding(plan_id, code, wgt_pct, fund_amount, shares, nav)
                    # 写全局 holdings(每日顾问跟踪)
                    self._sync_global_holding(code, fund_amount, shares, nav)
                spent_this += fund_amount
            total_spent += spent_this

            tr.amount = spent_this
            tr.status = "executed"
            tr.executed_at = datetime.utcnow()
            executed_txn.append(tr.concise())

        # 扣余额
        new_used = Decimal(str(plan.used_amount or 0)) + total_spent
        plan.used_amount = new_used
        plan.remaining = Decimal(str(plan.total_budget)) - new_used
        if plan.remaining <= Decimal("0"):
            plan.status = "completed"
        else:
            plan.status = "active"
        if not plan.approved_at:
            plan.approved_at = datetime.utcnow()
        self.db.commit()

        return {
            "plan_id": plan_id,
            "status": plan.status,
            "used_amount": float(plan.used_amount),
            "remaining": float(plan.remaining),
            "executed": executed_txn,
        }

    # ─────────────────────────────────────────
    #  工具
    # ─────────────────────────────────────────
    def _latest_nav(self, fund_code: str):
        from backend.models.nav_history import FundNavHistory
        row = self.db.execute(
            select(FundNavHistory.unit_nav)
            .where(FundNavHistory.fund_code == fund_code)
            .order_by(FundNavHistory.nav_date.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row:
            return row
        # 主库无历史 -> 从临时表(回测/荐基自动拉取的候选基金)取最新净值
        from backend.models.sim_tmp_fund import SimTmpFund
        import json as _json
        tmp = self.db.execute(
            select(SimTmpFund.nav_json).where(
                SimTmpFund.fund_code == fund_code
            )
        ).scalar_one_or_none()
        if tmp:
            try:
                arr = _json.loads(tmp)
                if arr:
                    # arr 形如 [{"d":"date","n":1.9,...}], 取最后一条即最新
                    return Decimal(str(arr[-1]["n"]))
            except Exception:
                pass
        # 主库+临时表都没有(如用户未回测直接建仓) -> 实时从天天基金拉最新净值
        try:
            from backend.services.nav_fetcher import fetch_latest_nav
            import asyncio, httpx

            nav = None
            async def _go():
                async with httpx.AsyncClient(timeout=25) as c:
                    return await fetch_latest_nav(c, fund_code)
            nd = asyncio.run(_go())
            if nd and nd.unit_nav:
                return Decimal(str(nd.unit_nav))
        except Exception:
            pass
        return None

    def _upsert_plan_holding(self, plan_id, code, wgt_pct, amount, shares, nav):
        row = self.db.execute(
            select(PlanHolding).where(
                PlanHolding.plan_id == plan_id, PlanHolding.fund_code == code
            )
        ).scalar_one_or_none()
        name = self._fund_name(code)
        if row:
            new_cost = Decimal(str(row.total_cost or 0)) + amount
            new_units = Decimal(str(row.total_units or 0)) + shares
            row.total_cost = new_cost
            row.total_units = new_units
            row.avg_cost = (new_cost / new_units) if new_units > 0 else Decimal("0")
            row.last_nav = nav
            row.last_update = datetime.utcnow()
        else:
            row = PlanHolding(
                plan_id=plan_id, fund_code=code, fund_name=name,
                total_cost=amount, total_units=shares, avg_cost=(amount / shares) if shares else Decimal("0"),
                last_nav=nav, last_update=datetime.utcnow(),
            )
            self.db.add(row)

    def _sync_global_holding(self, fund_code, amount, shares, nav):
        """写全局 holdings(每日顾问整体分析用)。简单策略: 按计划批次新增一条持仓。"""
        from backend.models.holding import FundHolding
        name = self._fund_name(fund_code)
        # 尝试归并到已有同基金持仓, 否则新建
        existing = self.db.execute(
            select(FundHolding)
            .where(FundHolding.fund_code == fund_code, FundHolding.status == 1)
            .order_by(FundHolding.id.desc())
        ).scalars().first()
        share_date = datetime.now().date()
        if existing:
            existing.shares = Decimal(str(existing.shares or 0)) + shares
            existing.market_value = Decimal(str(existing.market_value or 0)) + amount
        else:
            h = FundHolding(
                fund_code=fund_code, fund_name=name,
                share_type="前收费", platform="投资方案(RFC-018)",
                fund_account="plan-" + str(fund_code), trade_account="plan-" + str(fund_code),
                shares=shares, share_date=share_date,
                nav_on_import=nav, cost_nav=nav, market_value=amount,
                status=1,
            )
            self.db.add(h)

    def _fund_name(self, fund_code: str) -> str:
        row = self.db.execute(
            select(FundCandidate.fund_name).where(FundCandidate.fund_code == fund_code)
        ).scalar_one_or_none()
        if row:
            return row
        from backend.models.fund import Fund
        row2 = self.db.execute(
            select(Fund.fund_name).where(Fund.fund_code == fund_code)
        ).scalar_one_or_none()
        return row2 or fund_code

    # ─────────────────────────────────────────
    #  查询
    # ─────────────────────────────────────────
    def get_plan(self, plan_id: int) -> Optional[dict]:
        plan = self.db.execute(
            select(PortfolioPlan).where(PortfolioPlan.id == plan_id)
        ).scalar_one_or_none()
        if not plan:
            return None
        tranches = self.db.execute(
            select(PlanTranche)
            .where(PlanTranche.plan_id == plan_id)
            .order_by(PlanTranche.tranche_no.asc())
        ).scalars().all()
        holdings = self.db.execute(
            select(PlanHolding).where(PlanHolding.plan_id == plan_id)
        ).scalars().all()
        return {
            **plan.concise(),
            "tranches": [t.concise() for t in tranches],
            "holdings": [h.concise() for h in holdings],
        }

    def list_plans(self, status: Optional[str] = None) -> List[dict]:
        q = select(PortfolioPlan).order_by(PortfolioPlan.created_at.desc())
        if status:
            q = q.where(PortfolioPlan.status == status)
        plans = self.db.execute(q).scalars().all()
        return [p.concise() for p in plans]


def _composite_window(fund_windows: Dict[str, str]) -> str:
    """组合级择时档位(优先级 avoid > staged > now 估算, 简化)。"""
    windows = set(fund_windows.values()) if fund_windows else {DEFAULT_WINDOW}
    if "avoid" in windows and len(windows) == 1:
        return "avoid"
    if windows == {"avoid", "now_entry"}:
        # 有停投也有可投, 取保守
        return "wait" if "wait" not in windows else "wait"
    if "wait" in windows:
        return "wait"
    if "avoid" in windows:
        return "wait"
    if "now_entry" in windows and len(windows) == 1:
        return "now_entry"
    return DEFAULT_WINDOW
