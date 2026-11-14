"""add gallery_likes and user is_staff

Revision ID: 236505324235
Revises: de04c22496bc
Create Date: 2026-11-14 22:29:55.534036

ADR-0001 内容发现层：
- gallery_likes：登录用户对画廊行程布尔点赞（trip_id+user_id 唯一，幂等 toggle；
  独立于 trip_ratings 评分，不参与 hot 排序）。
- users.is_staff：运营编辑能力标记（staff 可对任意公开行程标 featured），
  经 env STAFF_USER_IDS 白名单启动同步授予，不建管理后台。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '236505324235'
down_revision: str | None = 'de04c22496bc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 防御式幂等（项目哲学）：`create_all` 可能已建表/索引/列，先查后建
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('gallery_likes'):
        op.create_table(
            'gallery_likes',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('trip_id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.String(length=36), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'trip_id', name='uq_gallery_likes_user_trip'),
        )
    existing_indexes = {ix['name'] for ix in sa.inspect(bind).get_indexes('gallery_likes')}
    if op.f('ix_gallery_likes_trip_id') not in existing_indexes:
        op.create_index(op.f('ix_gallery_likes_trip_id'), 'gallery_likes', ['trip_id'], unique=False)
    if op.f('ix_gallery_likes_user_id') not in existing_indexes:
        op.create_index(op.f('ix_gallery_likes_user_id'), 'gallery_likes', ['user_id'], unique=False)

    # users.is_staff：仅当列不存在时添加（create_all 可能已带该列）
    user_cols = {c['name'] for c in sa.inspect(bind).get_columns('users')}
    if 'is_staff' not in user_cols:
        op.add_column('users', sa.Column('is_staff', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'is_staff')
    op.drop_index(op.f('ix_gallery_likes_user_id'), table_name='gallery_likes')
    op.drop_index(op.f('ix_gallery_likes_trip_id'), table_name='gallery_likes')
    op.drop_table('gallery_likes')