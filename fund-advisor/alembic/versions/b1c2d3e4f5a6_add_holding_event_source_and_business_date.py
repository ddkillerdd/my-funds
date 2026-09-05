"""add source and business date to holdings and holding changes

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-09-04 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """以可回滚的加法方式增加来源和业务日期字段并回填历史数据。"""
    bind = op.get_bind()
    invalid_date_count = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM holding_changes c
            LEFT JOIN import_records i ON i.id = c.import_id
            WHERE c.created_at IS NULL
              AND (i.id IS NULL OR i.data_date IS NULL)
            """
        )
    ).scalar_one()
    if invalid_date_count:
        raise RuntimeError(
            "无法无损回填 holding_changes.business_date："
            f"有 {invalid_date_count} 条旧事件既无有效导入日期也无 created_at"
        )

    op.add_column(
        "fund_holdings",
        sa.Column("source_type", sa.String(length=20), nullable=True,
                  comment="file/manual/quick/legacy"),
    )
    op.execute(
        """
        UPDATE fund_holdings h
        LEFT JOIN import_records i ON i.id = h.last_import_id
        SET h.source_type = CASE
            WHEN i.id IS NOT NULL THEN 'file'
            ELSE 'legacy'
        END
        """
    )
    op.alter_column(
        "fund_holdings", "source_type", existing_type=sa.String(length=20),
        existing_nullable=True, nullable=False,
    )
    op.create_index(
        "idx_fh_source_type", "fund_holdings", ["source_type"], unique=False
    )

    op.alter_column(
        "holding_changes", "import_id", existing_type=sa.BigInteger(),
        existing_nullable=False, nullable=True,
    )
    op.execute("UPDATE holding_changes SET import_id = NULL WHERE import_id = 0")
    op.add_column(
        "holding_changes",
        sa.Column("business_date", sa.Date(), nullable=True, comment="业务发生日期"),
    )
    op.add_column(
        "holding_changes",
        sa.Column("source_type", sa.String(length=20), nullable=True,
                  comment="file/manual/quick/legacy"),
    )
    op.execute(
        """
        UPDATE holding_changes c
        LEFT JOIN import_records i ON i.id = c.import_id
        SET c.business_date = COALESCE(i.data_date, DATE(c.created_at)),
            c.source_type = CASE
                WHEN i.id IS NOT NULL THEN 'file'
                ELSE 'legacy'
            END
        """
    )
    op.execute(
        "UPDATE holding_changes SET source_type = 'legacy' "
        "WHERE source_type IS NULL"
    )
    op.alter_column(
        "holding_changes", "business_date", existing_type=sa.Date(),
        existing_nullable=True, nullable=False,
    )
    op.alter_column(
        "holding_changes", "source_type", existing_type=sa.String(length=20),
        existing_nullable=True, nullable=False,
    )
    op.create_index(
        "idx_hc_business_date", "holding_changes", ["business_date"], unique=False
    )
    op.create_index(
        "idx_hc_holding_business_id", "holding_changes",
        ["holding_id", "business_date", "id"], unique=False
    )


def downgrade() -> None:
    """仅在空 import_id 可安全处理时回滚，拒绝伪造旧导入编号。"""
    bind = op.get_bind()
    null_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM holding_changes WHERE import_id IS NULL")
    ).scalar_one()
    if null_count:
        raise RuntimeError(
            "无法无损恢复 holding_changes.import_id 非空约束："
            f"仍有 {null_count} 条手工/快捷/旧事件为空关联"
        )

    op.drop_index("idx_hc_holding_business_id", table_name="holding_changes")
    op.drop_index("idx_hc_business_date", table_name="holding_changes")
    op.drop_column("holding_changes", "source_type")
    op.drop_column("holding_changes", "business_date")
    op.alter_column(
        "holding_changes", "import_id", existing_type=sa.BigInteger(),
        existing_nullable=True, nullable=False,
    )
    op.drop_index("idx_fh_source_type", table_name="fund_holdings")
    op.drop_column("fund_holdings", "source_type")
