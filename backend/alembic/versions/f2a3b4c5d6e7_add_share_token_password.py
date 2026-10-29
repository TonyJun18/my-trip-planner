"""add share token password lock (task-share-gate-eval)

Revision ID: f2a3b4c5d6e7
Revises: c2d4e6f8a0b2
Create Date: 2026-10-29

task-share-gate-eval：分享/受邀编辑令牌可选密码锁（最小版）。
- share_tokens.password_hash：PBKDF2（复用 app.core.security.hash_password）。
  非空 = 该令牌已设访问密码；读取/协作/行中/地图编辑入口
  在生命周期门禁（过期 410 / 吊销 403）之后追加密码门禁（403 share_password_required）。
- 旧数据兼容：password_hash 默认 NULL = 未设锁，行为不变。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f2a3b4c5d6e7'
down_revision: str | None = 'c2d4e6f8a0b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 防御式幂等：create_all 可能先建列（项目哲学：先查后改）
    bind = op.get_bind()
    cols = [c["name"] for c in bind.dialect.get_columns(bind, "share_tokens")]
    if "password_hash" not in cols:
        op.add_column(
            'share_tokens',
            sa.Column('password_hash', sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    op.drop_column('share_tokens', 'password_hash')