"""基金候选池模型 (RFC-018 ① 基金池).

全市场候选基金元信息, 供 AI 主动荐基的数据源。
与主库 `funds`(真实持仓)隔离: 这里只存"候选元信息", 净值按需拉取缓存。
"""

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, Numeric, String, Text, func

from backend.database import Base


class FundCandidate(Base):
    __tablename__ = "fund_candidate"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fund_code = Column(String(10), nullable=False, unique=True, index=True)
    fund_name = Column(String(200), nullable=False, default="")
    fund_type = Column(String(50), default=None)      # 股票/混合/债券/指数/QDII/商品
    style = Column(String(50), default=None)          # 风格标签: 大盘/小盘/成长/价值
    scale = Column(Numeric(16, 2), default=None)      # 规模(亿)
    inception_date = Column(Date, default=None)       # 成立日
    latest_nav = Column(Numeric(10, 4), default=None)
    nav_change_pct = Column(Numeric(8, 4), default=None)
    label = Column(String(200), default=None)         # 行业/主题标签(逗号分隔)
    open_apply = Column(Integer, default=1)           # 是否开放申购
    status = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    @classmethod
    def upsert(cls, session, fund_code: str, fund_name: str, **kwargs):
        """按 fund_code 写或更新一条候选(唯一键)。
        kwargs 可传: fund_type/style/scale/inception_date/latest_nav/nav_change_pct/label/open_apply。
        """
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        values = {
            "fund_code": fund_code,
            "fund_name": fund_name,
        }
        values.update(kwargs)
        stmt = mysql_insert(cls).values(**values)
        update_cols = dict(values)
        update_cols.pop("fund_code", None)
        stmt = stmt.on_duplicate_key_update(**{
            k: v for k, v in update_cols.items() if v is not None
        })
        session.execute(stmt)
        session.commit()
