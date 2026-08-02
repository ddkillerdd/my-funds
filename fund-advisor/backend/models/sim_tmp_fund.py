"""临时基金存储模型 — 供"策略回测"模块拉取任意基金用。

设计原则:
  - 与主库 `funds` / `fund_nav_history` **完全隔离**, 不污染真实持仓数据。
  - `is_tmp=1` 打标记, 表示"仅用于单次模拟, 用后可清理"。
  - 历史净值以 JSON 存于一列, 避免建大量行, 便于"用完即删、避免冗余"。
"""

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from backend.database import Base


class SimTmpFund(Base):
    __tablename__ = "sim_tmp_fund"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fund_code = Column(String(10), nullable=False, unique=True)
    fund_name = Column(String(200), nullable=False, default="")
    is_tmp = Column(Integer, nullable=False, default=1, comment="标记:仅用于模拟, 用后可清理")
    # 历史净值序列 JSON: [{"date":"2025-01-01","unit_nav":1.23,"acc_nav":1.5,"change_pct":0.5}, ...] 升序
    nav_json = Column(Text, nullable=False, default="[]")
    nav_days = Column(Integer, nullable=False, default=0)
    first_nav_date = Column(Date, default=None)
    last_nav_date = Column(Date, default=None)
    created_at = Column(DateTime, server_default=func.now())
    last_used_at = Column(DateTime, server_default=func.now())

    @classmethod
    def upsert(cls, session, fund_code: str, fund_name: str, nav_json: str,
               nav_days: int, first_date, last_date, now):
        """写或更新一条临时基金记录(唯一键 fund_code)。"""
        stmt = mysql_insert(cls).values(
            fund_code=fund_code,
            fund_name=fund_name,
            is_tmp=1,
            nav_json=nav_json,
            nav_days=nav_days,
            first_nav_date=first_date,
            last_nav_date=last_date,
            created_at=now,
            last_used_at=now,
        )
        update_cols = {
            "fund_name": fund_name,
            "is_tmp": 1,
            "nav_json": nav_json,
            "nav_days": nav_days,
            "first_nav_date": first_date,
            "last_nav_date": last_date,
            "last_used_at": now,
        }
        stmt = stmt.on_duplicate_key_update(**update_cols)
        session.execute(stmt)
        session.commit()
