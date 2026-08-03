"""PlanHolding model - 计划持仓明细 (RFC-018).

每个计划的每只基金成本/份额/浮盈分开记录, 独立核算, 不与全局 holdings 混账。
每日顾问跟踪 plan 时, 直接读本表算该计划的浮盈:
    float_pnl = (last_nav - avg_cost) * total_units
"""

from datetime import datetime

from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey, Index

from backend.database import Base


class PlanHolding(Base):
    __tablename__ = "plan_holding"
    __table_args__ = (
        Index("idx_plan_holding_plan", "plan_id"),
        Index("idx_plan_holding_fund", "fund_code"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    plan_id = Column(BigInteger, ForeignKey("portfolio_plan.id"), nullable=False, index=True)
    fund_code = Column(String(10), nullable=False, index=True)
    fund_name = Column(String(200))

    # 本次计划累计投入该基金
    total_cost = Column(Numeric(14, 2), default=0, comment="已投入成本")
    total_units = Column(Numeric(16, 4), default=0, comment="累计份额(按各批成交净值折算)")
    avg_cost = Column(Numeric(10, 4), default=0, comment="平均成本 = total_cost/total_units")
    last_nav = Column(Numeric(10, 4), default=None, comment="最近净值(每日顾问更新)")
    last_update = Column(DateTime, default=None)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def concise(self) -> dict:
        float_pnl = None
        float_pnl_pct = None
        if self.last_nav is not None and self.avg_cost and self.avg_cost > 0:
            float_pnl = (float(self.last_nav) - float(self.avg_cost)) * float(self.total_units)
            float_pnl = round(float_pnl, 2)
            float_pnl_pct = round((float(self.last_nav) / float(self.avg_cost) - 1) * 100, 2)
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "total_cost": float(self.total_cost) if self.total_cost is not None else 0,
            "total_units": float(self.total_units) if self.total_units is not None else 0,
            "avg_cost": float(self.avg_cost) if self.avg_cost is not None else 0,
            "last_nav": float(self.last_nav) if self.last_nav is not None else None,
            "float_pnl": float_pnl,
            "float_pnl_pct": float_pnl_pct,
            "last_update": self.last_update.isoformat() if self.last_update else None,
        }
