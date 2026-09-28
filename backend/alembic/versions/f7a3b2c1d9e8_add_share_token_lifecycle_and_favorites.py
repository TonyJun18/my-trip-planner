"""add share token lifecycle and trip favorites

Revision ID: f7a3b2c1d9e8
Revises: d118b4b9aff7
Create Date: 2026-09-25 12:00:00.000000

方案 2（task-share-token-lifecycle）：分享令牌生命周期 + 收藏灵感夹。
- share_tokens：集中管理 share/edit 令牌的过期 / 吊销 / 最近使用时间（审计）。
  旧列 trips.share_token / trips.edit_token 保留（旧数据零迁移，按永久兼容）。
- trip_favorites：登录用户收藏他人分享的行程（灵感夹）。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f7a3b2c1d9e8'
down_revision: str | None = 'd118b4b9aff7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'share_tokens',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('trip_id', sa.String(length=36), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),  # share / edit
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_share_tokens_token'),
    )
    op.create_index(op.f('ix_share_tokens_trip_id'), 'share_tokens', ['trip_id'], unique=False)
    op.create_index(op.f('ix_share_tokens_kind'), 'share_tokens', ['kind'], unique=False)

    op.create_table(
        'trip_favorites',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('trip_id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'trip_id', name='uq_trip_favorites_user_trip'),
    )
    op.create_index(op.f('ix_trip_favorites_user_id'), 'trip_favorites', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trip_favorites_user_id'), table_name='trip_favorites')
    op.drop_table('trip_favorites')
    op.drop_index(op.f('ix_share_tokens_kind'), table_name='share_tokens')
    op.drop_index(op.f('ix_share_tokens_trip_id'), table_name='share_tokens')
    op.drop_table('share_tokens')