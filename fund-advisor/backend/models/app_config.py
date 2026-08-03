"""App Config — 简单 key-value 全局配置存储 (RFC-020).

用途: 用户可在前端设置"总资金"(可变输入), 每次分析动态读取, 无需改代码。
约定以 key 前缀区分业务; 本文件暂只承载投资相关可配置项。
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, DateTime
from backend.database import Base


class AppConfig(Base):
    __tablename__ = "app_config"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    key = Column(String(64), nullable=False, unique=True, comment="配置键, 如 total_capital_rmb")
    value = Column(Text, nullable=True, comment="配置值(字符串存储)")
    note = Column(String(200), nullable=True, comment="说明")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "note": self.note,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
