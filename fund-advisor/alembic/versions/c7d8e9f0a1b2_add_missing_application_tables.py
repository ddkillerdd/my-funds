"""补齐历史上由应用启动 create_all 隐式创建的业务表。

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-09-07 00:00:00.000000

旧启动路径会在 Alembic 之前调用 Base.metadata.create_all，导致初始迁移
遇到已存在的 fund_holdings。应用启动已不再写 schema，本迁移把仍未进入
迁移链的模型表收口到 Alembic 中。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from backend.database import Base
import backend.models  # noqa: F401  # 导入模型以注册完整 metadata


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """仅在迁移上下文中补齐缺失模型表，已有表保持不变。"""
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    missing_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in existing_tables
    ]
    if missing_tables:
        Base.metadata.create_all(bind=bind, tables=missing_tables, checkfirst=True)


def downgrade() -> None:
    """拒绝无备份删除业务表，回滚必须使用服务器备份恢复方案。"""
    raise RuntimeError(
        "c7d8e9f0a1b2 为业务表收口迁移，禁止直接降级删除数据；"
        "请使用已验证的服务器备份恢复方案。"
    )
