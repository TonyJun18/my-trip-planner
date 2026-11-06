"""add trip ratings

Revision ID: c2d4e6f8a0b2
Revises: b2c3d4e5f6a7
Create Date: 2026-10-29 00:30:00.000000

task-trip-rating-signal：行程评分 / 信任信号最小版。
- trip_ratings：登录用户对行程评分（1-5 星）+「我去过」标记（visited 布尔）。
  同 user + trip 唯一（可改分 / 可翻转 visited，幂等）；只读聚合
  （count / avg / visited_count）供画廊卡片透出热度，不改变行程可见性。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'c2d4e6f8a0b2'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 防御式幂等（项目哲学）：`create_all` 可能已建表/索引，先查后建
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('trip_ratings'):
        op.create_table(
            'trip_ratings',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('trip_id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.String(length=36), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),  # 1-5
            sa.Column('visited', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'trip_id', name='uq_trip_ratings_user_trip'),
        )
    existing_indexes = {ix['name'] for ix in sa.inspect(bind).get_indexes('trip_ratings')}
    if op.f('ix_trip_ratings_trip_id') not in existing_indexes:
        op.create_index(op.f('ix_trip_ratings_trip_id'), 'trip_ratings', ['trip_id'], unique=False)
    if op.f('ix_trip_ratings_user_id') not in existing_indexes:
        op.create_index(op.f('ix_trip_ratings_user_id'), 'trip_ratings', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trip_ratings_user_id'), table_name='trip_ratings')
    op.drop_index(op.f('ix_trip_ratings_trip_id'), table_name='trip_ratings')
    op.drop_table('trip_ratings')