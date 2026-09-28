"""merge two heads: plan_task events (a3f9c2e7b1d4) + share token lifecycle (f7a3b2c1d9e8)

Revision ID: b5c4d3e2f1a0
Revises: a3f9c2e7b1d4, f7a3b2c1d9e8
Create Date: 2026-09-25 12:30:00.000000

两个并行分支在 main 的 d118b4b9aff7 之后各自加列/建表，互不冲突：
- a3f9c2e7b1d4: plan_tasks.events / plan_tasks.state（规划事件流）
- f7a3b2c1d9e8: share_tokens / trip_favorites（分享令牌生命周期 + 收藏）
本迁移仅合并 head，不包含任何 DDL。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'b5c4d3e2f1a0'
down_revision: str | None = ('a3f9c2e7b1d4', 'f7a3b2c1d9e8')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass