"""Config Service — AppConfig(key-value) 读写 (RFC-020)。

提供:
  - get_config(db, key)      读取单个
  - set_config(db, key, val) 写/更新
  - get_total_capital(db)    读取"总资金"(前端可调), 无则 None
供 API 层与 advisor_service 共用。
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.app_config import AppConfig

logger = logging.getLogger("fund.config")

# 配置键常量
KEY_TOTAL_CAPITAL = "total_capital_rmb"
# RFC-021: 可用增量资金(元)。与新语义解耦; 旧 total_capital_rmb 保留作历史兼容回退。
KEY_AVAILABLE_CAPITAL = "available_capital_rmb"


def get_config(db: Session, key: str) -> Optional[str]:
    row = db.execute(select(AppConfig).where(AppConfig.key == key)).scalar_one_or_none()
    return row.value if row else None


def set_config(db: Session, key: str, value: str, note: Optional[str] = None) -> AppConfig:
    """按键 upsert: 存在则更新 value/note, 不存在则新插。"""
    row = db.execute(select(AppConfig).where(AppConfig.key == key)).scalar_one_or_none()
    if row is None:
        row = AppConfig(key=key, value=value, note=note)
        db.add(row)
    else:
        row.value = value
        if note is not None:
            row.note = note
    db.commit()
    db.refresh(row)
    return row


def get_total_capital(db: Session) -> Optional[float]:
    """读取用户在前端设置的总资金(元); 未设置返回 None, 由调用方决定 fallback。"""
    raw = get_config(db, KEY_TOTAL_CAPITAL)
    if not raw:
        return None
    try:
        return float(Decimal(str(raw).strip()))
    except Exception:
        logger.warning("total_capital_rmb 配置值非法: %r", raw)
        return None


def set_total_capital(db: Session, value: float, note: str = "用户前端设置总资金") -> AppConfig:
    return set_config(db, KEY_TOTAL_CAPITAL, str(value), note)


def get_available_capital(db: Session) -> Optional[float]:
    """RFC-021: 读取用户在前端设置的「可用增量资金」(元), 即本次愿投入的子弹。
    优先新 key; 旧 total_capital_rmb 存在时作为回退(无新 key)。
    """
    raw = get_config(db, KEY_AVAILABLE_CAPITAL)
    if raw:
        try:
            return float(Decimal(str(raw).strip()))
        except Exception:
            logger.warning("available_capital_rmb 配置值非法: %r", raw)
    # 无新配置 → 回退旧 total_capital(旧语义即“愿投入总盘子”)
    return get_total_capital(db)


def set_available_capital(db: Session, value: float, note: str = "用户前端设置可用增量资金") -> AppConfig:
    return set_config(db, KEY_AVAILABLE_CAPITAL, str(value), note)
