"""HoldingChange model - tracks holding changes per import."""

from sqlalchemy import Column, BigInteger, String, Numeric, Date, DateTime, Index
from sqlalchemy.sql import func

from backend.database import Base


class HoldingChange(Base):
    __tablename__ = "holding_changes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(BigInteger, nullable=True, comment="文件导入时关联 import_records.id")
    holding_id = Column(BigInteger, comment="关联 fund_holdings.id")
    fund_code = Column(String(10), nullable=False)
    fund_name = Column(String(200))
    platform = Column(String(100))
    change_type = Column(String(20), nullable=False, comment="new/increase/decrease/clear")
    shares_before = Column(Numeric(16, 4))
    shares_after = Column(Numeric(16, 4))
    shares_delta = Column(Numeric(16, 4))
    nav_at_change = Column(Numeric(10, 4), comment="变动时净值")
    mv_before = Column(Numeric(16, 4))
    mv_after = Column(Numeric(16, 4))
    business_date = Column(Date, nullable=False, comment="业务发生日期")
    source_type = Column(String(20), nullable=False, comment="file/manual/quick/legacy")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_hc_import_id", "import_id"),
        Index("idx_hc_fund_code", "fund_code"),
        Index("idx_hc_business_date", "business_date"),
        Index("idx_hc_holding_business_id", "holding_id", "business_date", "id"),
    )
