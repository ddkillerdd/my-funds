"""EmailSendRecord model - dedupe guard so we never send >1 advisor email per day.

Each row records that an advisor-analysis email was successfully sent on a given
report date. Column `report_date` is UNIQUE so concurrent/retried runs cannot
insert duplicates (the DB enforces the daily lock even under race conditions).
"""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint

from backend.database import Base


class EmailSendRecord(Base):
    __tablename__ = "email_send_record"
    __table_args__ = (
        UniqueConstraint("report_date", name="uq_email_send_record_report_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_date = Column(Date, nullable=False, comment="报告对应日期（东八区当天）")
    model_used = Column(String(128), nullable=True, comment="本次使用的模型")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, comment="发送记录时间")
