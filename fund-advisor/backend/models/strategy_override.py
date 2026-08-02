"""StrategyOverride model - 某风险类别当前实际生效的策略参数 (RFC-017)。

报告侧(analyzer/advisor_service)在为某基金决策时, 读取其 risk_class 对应的
override; 若存在且 approved, 用它覆盖 decision 默认参数; 否则用保守默认。

只允许写入 source=approved 的记录(由采纳流程写入), 保证数据只来自用户确认。
"""

from datetime import datetime

from sqlalchemy import Column, BigInteger, Integer, String, Float, DateTime

from backend.database import Base


class StrategyOverride(Base):
    __tablename__ = "strategy_override"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    risk_class = Column(String(20), nullable=False, unique=True, comment="low/medium/high")
    target_vol = Column(Float, nullable=False)
    friction_band_pp = Column(Float, nullable=False)
    source = Column(String(20), default="approved", comment="只能 approved")
    proposal_id = Column(Integer, nullable=True, comment="来源 adaptive_proposal.id")
    note = Column(String(200), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "risk_class": self.risk_class,
            "target_vol": self.target_vol,
            "friction_band_pp": self.friction_band_pp,
            "source": self.source,
            "proposal_id": self.proposal_id,
            "note": self.note,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
