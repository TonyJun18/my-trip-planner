"""add trip_bookings table (task-booking-outlink)

Revision ID: b1c2d3e4f5a6
Revises: c3d4e5f6a7b8
Create Date: 2026-10-28
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: str | None = 'c3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 防御式幂等：create_all 可能先建表（项目哲学：has_table 检查后才 create）
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "trip_bookings"):
        return
    op.create_table(
        'trip_bookings',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('trips.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=True),
        sa.Column('provider_url', sa.String(length=500), nullable=True),
        sa.Column('order_no', sa.String(length=100), nullable=True),
        sa.Column('credential', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='suggested', index=True),
        sa.Column('reference', sa.String(length=20), nullable=False, server_default='plan.generated'),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='CNY'),
        sa.Column('probe_plan', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, index=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('trip_bookings')