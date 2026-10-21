"""add gallery fields to trips (task-gallery-featured)

Revision ID: e5b6c7d8e9f0
Revises: e4f5a6b7c8d9
Create Date: 2026-10-22
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b6c7d8e9f0'
down_revision: str | None = 'e4f5a6b7c8d9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 防御式幂等：create_all 可能先建表/加列（项目哲学：先查再加）
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("trips")}
    if "is_featured" not in cols:
        op.add_column("trips", sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.create_index(op.f("ix_trips_is_featured"), "trips", ["is_featured"])
    if "gallery_blurb" not in cols:
        op.add_column("trips", sa.Column("gallery_blurb", sa.String(length=200), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("trips")}
    if "gallery_blurb" in cols:
        op.drop_column("trips", "gallery_blurb")
    if "is_featured" in cols:
        op.drop_index(op.f("ix_trips_is_featured"), table_name="trips")
        op.drop_column("trips", "is_featured")