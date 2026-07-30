"""AdvisorReport model - persists AI analysis reports so they survive page refresh."""

from datetime import datetime

from sqlalchemy import Column, Integer, Text, DateTime, String

from backend.database import Base


class AdvisorReport(Base):
    __tablename__ = "advisor_report"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_json = Column(Text, nullable=False, comment="完整分析报告 JSON")
    model_used = Column(String(128), nullable=False, comment="生成报告的模型")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, comment="报告生成时间")
