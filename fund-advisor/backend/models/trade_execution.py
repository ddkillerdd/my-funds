"""trade_execution.py — 用户实际操作记录 (RFC-020 块C 核心闭环)。

记录"系统建议 vs 用户实际操作"的偏差。用户第6点核心诉求:
"我建议了你不一定照做, 要记录我实际的操作, 用于后续分析校准。"
两类来源:
  - manual:   前端口径回填(照做/没做/反向/自填金额)
  - diff:     后续真实加仓/减仓(record_change)时自动反推的动作与金额
"""
from datetime import datetime
from sqlalchemy import (
    Column, BigInteger, String, Float, Integer, DateTime, Index,
)

from backend.database import Base


class TradeExecution(Base):
    __tablename__ = "trade_execution"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    report_id = Column(BigInteger, nullable=False, index=True, comment="关联 advisor_report.id")
    report_date = Column(String(10), nullable=False, comment="报告所属交易日 YYYY-MM-DD")
    fund_code = Column(String(20), nullable=False, comment="基金代码")
    fund_name = Column(String(100), nullable=True)

    # 系统建议
    suggested_action = Column(String(20), nullable=True, comment="建议动作: increase/reduce/hold/watch")
    suggested_action_label = Column(String(20), nullable=True, comment="中文: 加仓/减仓/持有/观望")
    suggested_weight_pct = Column(Float, nullable=True, comment="建议目标仓位%")
    suggested_amount = Column(Float, nullable=True, comment="建议操作金额(元, 正加负减)")

    # 用户实际操作
    actual_action = Column(String(20), nullable=True,
                           comment="实际: same_as_suggest/increase/reduce/none(未动)/reversed(反向)")
    actual_action_label = Column(String(20), nullable=True, comment="中文")
    actual_amount = Column(Float, nullable=True, comment="实际操作金额(元, 0=未动, 负=减)")

    # 来源与元信息
    source = Column(String(10), default="manual",
                    comment="manual=前端回填 / diff=自动比对持仓变化反推")
    note = Column(String(300), nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_trade_exec_report_fund", "report_id", "fund_code"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "report_id": self.report_id,
            "report_date": self.report_date,
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "suggested_action": self.suggested_action,
            "suggested_action_label": self.suggested_action_label,
            "suggested_weight_pct": self.suggested_weight_pct,
            "suggested_amount": self.suggested_amount,
            "actual_action": self.actual_action,
            "actual_action_label": self.actual_action_label,
            "actual_amount": self.actual_amount,
            "source": self.source,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
