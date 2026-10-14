"""add inferred_preferences_json to user_profiles (task-preference-inference)

Revision ID: f9e8d7c6b5a4
Revises: d0e1f2a3b4c5
Create Date: 2026-10-14 10:00:00.000000

「知道你要什么」个性化引擎第一步：把行为记忆信号 → 规则推理 → 稳定偏好。
新增列 inferred_preferences_json（结构见 models/profile.py 注释）。
与 behavior_memory_json 同样的防御式写法：create_all 先行创建的新库跳过，
旧库幂等补列；列已存在则 no-op。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f9e8d7c6b5a4'
down_revision: str | None = 'd0e1f2a3b4c5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("user_profiles"):
        # 表都不存在 → create_all 会建（含本列），无需在此建表
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("user_profiles")}
    if "inferred_preferences_json" not in columns:
        op.add_column(
            "user_profiles",
            sa.Column("inferred_preferences_json", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("user_profiles"):
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("user_profiles")}
    if "inferred_preferences_json" in columns:
        op.drop_column("user_profiles", "inferred_preferences_json")