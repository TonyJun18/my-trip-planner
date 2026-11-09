"""收藏地点表（collect-first 底座）

Revision ID: d4e6f8a0b2c4
Revises: c3d5e7f9a1b2
Create Date: 2026-11-10 03:00:00.000000

task-social-favorites-flow-eval：Plotline collect-first 范式落地。
- favorite_spots：用户自己的「地点收集箱」——社交/笔记导入解析出的候选，
  行程未定时先攒着，行程确定后再转（与 favorites-to-route 的「收藏行程→
  一键成路线」衔接成完整 collect-first 链路）。
- 与 trip_favorites 分离：trip_favorites 收藏「行程」（只读引用他人分享），
  favorite_spots 收藏「地点」（用户自己的结构化候选）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e6f8a0b2c4"
down_revision: str | None = "c3d5e7f9a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "favorite_spots"


def upgrade() -> None:
    # 防御式幂等：create_all 可能已建表（项目哲学：先查后建）
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_key", sa.String(length=200), nullable=False),
        sa.Column("stop_type", sa.String(length=20), nullable=False, server_default="attraction"),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("source_platform", sa.String(length=20), nullable=True),
        sa.Column("source_snippet", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name_key", name="uq_favorite_spots_user_name"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        op.drop_table(_TABLE)