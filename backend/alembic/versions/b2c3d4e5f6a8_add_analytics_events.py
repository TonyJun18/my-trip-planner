"""add analytics_events table (task-launch-deploy-eval)

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-11-21

最小漏斗埋点落库表：5 类白名单事件（page_view/register/plan_submitted/
plan_completed/share_created）。匿名可记录，故 user_id/trip_id 可空且无外键。
防御式幂等：create_all 可能先建表（与 trip_events 迁移同模板）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a8"
down_revision: str | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "analytics_events"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.has_table(bind, _TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_name", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("trip_id", sa.String(length=36), nullable=True),
        sa.Column("anonymous_session_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_analytics_events_name_created", _TABLE, ["event_name", "created_at"]
    )
    op.create_index(
        "ix_analytics_events_anonymous_session", _TABLE, ["anonymous_session_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, _TABLE):
        return
    op.drop_index("ix_analytics_events_anonymous_session", table_name=_TABLE)
    op.drop_index("ix_analytics_events_name_created", table_name=_TABLE)
    op.drop_table(_TABLE)
