"""add events and state to plan_tasks

Revision ID: a3f9c2e7b1d4
Revises: d118b4b9aff7
Create Date: 2026-09-25 10:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f9c2e7b1d4'
down_revision: str | None = 'd118b4b9aff7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 规划过程事件流(阶段/制品;供轮询快照读取,前端渲染阶段状态机视图)
    op.add_column('plan_tasks', sa.Column('events', sa.JSON(), nullable=True))
    # 2期检查点门控预留:collecting/awaiting_review/assembling/reviewing/completed
    op.add_column('plan_tasks', sa.Column('state', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('plan_tasks', 'state')
    op.drop_column('plan_tasks', 'events')