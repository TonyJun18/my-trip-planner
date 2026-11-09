"""机票特价快照（FlightDeals 采集缓存）

Revision ID: c3d5e7f9a1b2
Revises: b5c6d7e8f9a0
Create Date: 2026-11-09 14:30:00.000000

为什么落库而不是纯内存：
- 服务重启后仍能展示「上次采集到的方案」，避免每次规划都重新打外部搜索；
- 可审计：``fetched_at`` / ``provider`` / ``hit_count`` 让前端能标「采集于 x 分钟前」；
- 口径：payload 里每条 option 都带 source_url + price_kind=from，绝不当作实时报价。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d5e7f9a1b2"
down_revision: str | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "flight_deal_snapshots"


def upgrade() -> None:
    # 防御式幂等：create_all 可能已建表（项目哲学：先查后建）
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("route_key", sa.String(length=256), nullable=False, index=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="tavily"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="degraded"),
        sa.Column("options_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        op.drop_table(_TABLE)
