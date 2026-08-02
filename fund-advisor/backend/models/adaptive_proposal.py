"""AdaptiveProposal model - WFA 自适应参数推荐记录 (RFC-017)。

每次对某风险类别跑 Walk-Forward 自适应优化后, 把"推荐参数 + 样本外证据"落一条记录,
状态 pending(待用户确认) → approved(已采纳, 报告侧生效) / rejected(已否决)。

只有 approved 的参数才会被报告侧使用; pending/rejected 一律不生效 —— 保证
"未经验证/未确认的参数永不进入实盘" (甲方案·半自动模式 X)。
"""

from datetime import datetime

from sqlalchemy import Column, BigInteger, Integer, String, Numeric, Float, DateTime, Text, Index

from backend.database import Base


class AdaptiveProposal(Base):
    __tablename__ = "adaptive_proposal"
    __table_args__ = (
        Index("idx_ap_status", "status"),
        Index("idx_ap_class", "risk_class"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    risk_class = Column(String(20), nullable=False, comment="low/medium/high 波动类")
    fund_codes = Column(Text, comment="参与该次优化的基金代码(逗号分隔)")

    # WFA 推荐参数
    target_vol = Column(Float, comment="推荐 target_vol")
    friction_band_pp = Column(Float, comment="推荐 friction_band_pp")
    default_target_vol = Column(Float, comment="该类保守默认 target_vol(对照)")
    default_friction_band_pp = Column(Float, comment="该类保守默认 friction")

    # 样本外证据
    avg_test_excess_pct = Column(Float, comment="样本外超额(相对死拿)%")
    best_max_drawdown = Column(Float, comment="样本外最大回撤(小数)")
    best_wfe = Column(Float, comment="WFE 效率(0~1)")
    train_days = Column(Integer, comment="训练段天数")
    test_days = Column(Integer, comment="测试段天数")
    data_start = Column(String(20), comment="数据起始")
    data_end = Column(String(20), comment="数据结束")

    # 校验结论
    passed = Column(Integer, default=0, comment="1=通过 0=未通过(未通过不会建议采用)")
    reasons = Column(Text, comment="未通过/需注意的理由")
    notes = Column(Text, comment="通过的理由/明细")

    # 状态机
    status = Column(String(20), default="pending", comment="pending/approved/rejected")
    decided_at = Column(DateTime, nullable=True, comment="用户确认时间")
    decided_note = Column(String(500), nullable=True, comment="用户确认备注")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def concise(self) -> dict:
        """返回给前端展示的精简结构。"""
        return {
            "id": self.id,
            "risk_class": self.risk_class,
            "fund_codes": (self.fund_codes or "").split(",") if self.fund_codes else [],
            "target_vol": self.target_vol,
            "friction_band_pp": self.friction_band_pp,
            "default_target_vol": self.default_target_vol,
            "default_friction_band_pp": self.default_friction_band_pp,
            "avg_test_excess_pct": self.avg_test_excess_pct,
            "best_max_drawdown": self.best_max_drawdown,
            "best_wfe": self.best_wfe,
            "train_days": self.train_days,
            "test_days": self.test_days,
            "data_start": self.data_start,
            "data_end": self.data_end,
            "passed": bool(self.passed),
            "reasons": (self.reasons or "").split("\n") if self.reasons else [],
            "notes": (self.notes or "").split("\n") if self.notes else [],
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
