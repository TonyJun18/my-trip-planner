"""add trip_passports table (task-journey-passport)

Revision ID: b2c3d4e5f6a7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-28
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'b1c2d3e4f5a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 防御式幂等：create_all 可能先建表（项目哲学：has_table 检查后才 create）
    bind = op.get_bind()
    if bind.dialect.has_table(bind, "trip_passports"):
        return
    op.create_table(
        'trip_passports',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('trip_id', sa.String(length=36), sa.ForeignKey('trips.id', ondelete='CASCADE'), nullable=False, unique=True, index=True),
        sa.Column('phase', sa.String(length=20), nullable=False, server_default='upcoming'),
        sa.Column('badges', sa.JSON(), nullable=True),
        sa.Column('last_progress_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('share_token', sa.String(length=64), nullable=True, unique=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('trip_passports')