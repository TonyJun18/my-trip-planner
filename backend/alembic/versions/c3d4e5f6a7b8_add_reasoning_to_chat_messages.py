"""add reasoning to chat_messages

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-10-28 14:00:00.000000

背景：AI 助手 B 期对话增加「思考过程」展示——推理模型（DeepSeek reasoner /
OpenAI reasoning）在正文之外返回 reasoning_content；把该文本落到
chat_messages.reasoning 列，历史消息可折叠回看，出错时可追溯模型思考。

设计（对齐既有迁移惯例）：
- 只加一列，nullable、Text、无 server_default（历史行视为无思考过程）
- downgrade 仅删列
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: str | None = 'b7c8d9e0f1a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('chat_messages', sa.Column('reasoning', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_messages', 'reasoning')