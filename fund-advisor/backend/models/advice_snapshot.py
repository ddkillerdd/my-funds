"""AdviceSnapshot model - records each directional advice for later backtest (RFC-012).

Written when a report is generated (record_advice). After T+N days the integration
layer validates pending rows against actual NAV moves and sets the verdict.
"""

from datetime import datetime

from sqlalchemy import Column, BigInteger, Integer, String, Numeric, DateTime, Date, Index

from backend.database import Base


class AdviceSnapshot(Base):
    __tablename__ = "advice_snapshot"
    __table_args__ = (
        Index("idx_as_report", "report_id"),
        Index("idx_as_status", "status"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    report_id = Column(Integer, nullable=True, comment="关联 advisor_report.id")
    fund_code = Column(String(20), nullable=False)
    fund_name = Column(String(200))
    action = Column(String(20), nullable=False, comment="reduce/increase/hold/watch")
    advice_date = Column(Date, nullable=False, comment="建议日(报告日)")
    nav_at_advice = Column(Numeric(10, 4), comment="建议时基金单位净值")
    change_pct = Column(Numeric(8, 2), nullable=True, comment="建议调仓幅度% (REDUCE/INCREASE)")
    benchmark_name = Column(String(50), default="沪深300", comment="对比基准")

    # validation
    status = Column(String(20), default="pending", comment="pending/validated/expired")
    validation_date = Column(Date, nullable=True, comment="验证日")
    nav_at_validation = Column(Numeric(10, 4), comment="验证时基金单位净值")
    benchmark_at_advice = Column(Numeric(12, 4), comment="建议时基准点位")
    benchmark_at_validation = Column(Numeric(12, 4), comment="验证时基准点位")
    fund_change_pct = Column(Numeric(10, 4), comment="建议后基金涨跌%")
    benchmark_change_pct = Column(Numeric(10, 4), comment="建议后基准涨跌%")
    relative_return = Column(Numeric(10, 4), comment="基金涨跌-基准涨跌")
    verdict = Column(String(20), nullable=True, comment="hit/miss/neutral")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
