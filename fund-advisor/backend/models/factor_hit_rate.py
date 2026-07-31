"""FactorHitRate model - persistent state for on-line learning (RFC-012).

Stores how often each dimension / action type was historically a hit, updated on
the 10-day adaptation job. The integration layer reads this to calibrate
confidence and view emphasis on the next analysis.
"""

from datetime import datetime

from sqlalchemy import Column, BigInteger, String, Integer, Numeric, DateTime, UniqueConstraint

from backend.database import Base


class FactorHitRate(Base):
    __tablename__ = "factor_hit_rate"
    __table_args__ = (
        UniqueConstraint("factor_key", "action_type", name="uq_fhr_key_action"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    factor_key = Column(String(50), nullable=False, comment="趋势维度, 如 trend/risk/value/tech/sharpe")
    action_type = Column(String(20), nullable=False, comment="reduce/increase（方向动作）")
    total = Column(Integer, default=0, comment="方向判定总次数")
    hits = Column(Integer, default=0, comment="命中次数")
    miss = Column(Integer, default=0, comment="未命中次数")
    hit_rate = Column(Numeric(6, 4), nullable=True, comment="命中率(0-1)")
    rolling_window = Column(Integer, default=20, comment="滚动窗口大小")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
