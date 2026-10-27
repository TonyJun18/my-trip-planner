"""add trip_expenses

Revision ID: a1b2c3d4e5f6
Revises: e5b6c7d8e9f0
Create Date: 2026-10-24 01:00:00.000000

task-expense-split-mini：行中费用记录与人均结余（Stippl/MonkeyTravel 行中一体化）。
- trip_expenses：行程实际花费（金额/类别/支付人/备注），挂 trip_id（不挂 day_id）。
- payer 为自由文本姓名（零凭证零成员表）；空串 = 未指定，不参与分摊。
- category: food/transport/hotel/attraction/shopping/other（默认 other）。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = 'e5b6c7d8e9f0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'trip_expenses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('trip_id', sa.String(length=36), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False, server_default='other'),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('payer', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_trip_expenses_trip_id'), 'trip_expenses', ['trip_id'], unique=False)
    op.create_index(op.f('ix_trip_expenses_created_at'), 'trip_expenses', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trip_expenses_created_at'), table_name='trip_expenses')
    op.drop_index(op.f('ix_trip_expenses_trip_id'), table_name='trip_expenses')
    op.drop_table('trip_expenses')