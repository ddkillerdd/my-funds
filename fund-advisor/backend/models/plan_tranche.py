"""PlanTranche model - 分批批次 (且慢"100份") (RFC-018).

一张投资计划拆成多批执行, 每批按择时信号(dca_planner 估值法)决定投几份。
window 复用现有择时档位: now_entry/staged_entry/wait/avoid。
dca_multiplier: 倍率 0.6/1.0/1.3 (来自 dca_planner.base_amount_pct)。
状态机: pending(待执行) -> executed(已执行)。
"""

from datetime import datetime

from sqlalchemy import Column, BigInteger, Integer, String, Numeric, Date, DateTime, ForeignKey, Index

from backend.database import Base


class PlanTranche(Base):
    __tablename__ = "plan_tranche"
    __table_args__ = (
        Index("idx_tranche_plan", "plan_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    plan_id = Column(BigInteger, ForeignKey("portfolio_plan.id"), nullable=False, index=True)
    tranche_no = Column(Integer, comment="批次序号 1..N")

    # 分批参数
    units = Column(Numeric(10, 2), comment="应投份数(展示: 本批金额/unit)")
    window = Column(String(30), comment="择时: now_entry/staged_entry/wait/avoid")
    dca_multiplier = Column(Numeric(4, 2), comment="倍率: 0.6/1.0/1.3 (来自 dca_planner)")
    plan_date = Column(Date, comment="建议执行日")

    # 执行状态
    status = Column(String(20), default="pending", comment="pending/executed")
    executed_at = Column(DateTime, default=None)
    amount = Column(Numeric(14, 2), default=None, comment="实际投入金额")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def concise(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "tranche_no": self.tranche_no,
            "units": float(self.units) if self.units is not None else None,
            "window": self.window,
            "dca_multiplier": float(self.dca_multiplier) if self.dca_multiplier is not None else None,
            "plan_date": str(self.plan_date) if self.plan_date else None,
            "status": self.status,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "amount": float(self.amount) if self.amount is not None else None,
        }
