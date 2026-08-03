"""PortfolioPlan model - 投资计划(固定预算) (RFC-018).

用户的一份长期投资方案: 固定预算 + 风险偏好 -> 选基/配比/分批/建仓。
状态机: draft(草稿) -> active(已确认建仓, 分批执行中) -> completed(完成)。
target_allocation 存 {fund_code: weight_pct} 配比。
"""

from datetime import datetime

from sqlalchemy import Column, BigInteger, String, Numeric, Text, DateTime, JSON, Index

from backend.database import Base


class PortfolioPlan(Base):
    __tablename__ = "portfolio_plan"
    __table_args__ = (
        Index("idx_plan_status", "status"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), default="我的入场计划")
    total_budget = Column(Numeric(14, 2), comment="固定预算(如 100)")
    used_amount = Column(Numeric(14, 2), default=0, comment="已投入")
    remaining = Column(Numeric(14, 2), comment="剩余 = total - used")
    risk_profile = Column(String(20), default="balanced",
                          comment="用户风险偏好: conservative/balanced/aggressive (UI层)")
    status = Column(String(20), default="draft", comment="draft/active/completed")
    target_allocation = Column(JSON, comment="{fund_code: weight_pct}")
    ai_summary = Column(Text, default=None, comment="AI 生成的方案解读/理由")
    approved_at = Column(DateTime, default=None)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def concise(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "total_budget": float(self.total_budget) if self.total_budget is not None else None,
            "used_amount": float(self.used_amount) if self.used_amount is not None else 0,
            "remaining": float(self.remaining) if self.remaining is not None else None,
            "risk_profile": self.risk_profile,
            "status": self.status,
            "target_allocation": self.target_allocation or {},
            "ai_summary": self.ai_summary,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
