"""add departure / trip_type to trips (task-departure-trip-type)

Revision ID: d0e1f2a3b4c5
Revises: c7a9d1e2b3f4
Create Date: 2026-10-03 22:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'd0e1f2a3b4c5'
down_revision: str | None = 'c7a9d1e2b3f4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # trips 表可能已由 create_all 建出（create_all 只建缺失表、不给已有表加列）；
    # 幂等：列已存在则跳过。
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("trips"):
        # 表都没建 → 首次迁移会建含本列的表，无需在此补列
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("trips")}
    if "departure" not in columns:
        op.add_column("trips", sa.Column("departure", sa.String(length=200), nullable=True))
    if "trip_type" not in columns:
        op.add_column("trips", sa.Column("trip_type", sa.String(length=20), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("trips"):
        columns = {c["name"] for c in sa.inspect(bind).get_columns("trips")}
        if "trip_type" in columns:
            op.drop_column("trips", "trip_type")
        if "departure" in columns:
            op.drop_column("trips", "departure")