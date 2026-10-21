"""add trip_events table (task-trip-event-notify)

Revision ID: e4f5a6b7c8d9
Revises: f9e8d7c6b5a4
Create Date: 2026-10-22
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e4f5a6b7c8d9'
down_revision: str | None = 'f9e8d7c6b5a4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 防御式幂等：create_all 可能先建表（项目哲学：has_table 检查后才 create）
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "trip_events"):
        return
    op.create_table(
        'trip_events',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('trips.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('event_type', sa.String(length=20), nullable=False, index=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table('trip_events')