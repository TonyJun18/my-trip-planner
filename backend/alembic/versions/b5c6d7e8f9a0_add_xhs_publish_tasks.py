"""add xhs_publish_tasks (local publisher / browser extension mode)

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-09 05:10:00.000000

本机发布器模式：服务端只存"要发什么"，账号凭证始终留在用户自己的浏览器里。
任务由用户浏览器中的扩展领取、填表、发布，再回写状态。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "xhs_publish_tasks"


def upgrade() -> None:
    # 防御式幂等：create_all 可能已建表（项目哲学：先查后建）
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("trip_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("asset_ids", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="pending", index=True),
        sa.Column("note_url", sa.String(length=512), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("agent", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        op.drop_table(_TABLE)
