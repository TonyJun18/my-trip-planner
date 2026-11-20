"""trip_bookings 增 free_cancel_deadline（免费取消截止日）

Revision ID: a1b2c3d4e5f7
Revises: 236505324235
Create Date: 2026-11-20 12:00:00.000000

task-free-cancel-deadline-eval（Everway「reminds before free cancellation ends」）：
- free_cancel_deadline：免费取消截止日（DATE，可空，索引），台账倒计时键 +
  截止前提醒（basis=rule_based）；不参与状态机判定（与凭证防线无关）。
- 可空：存量行零回填，可 downgrade。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "236505324235"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "trip_bookings"


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    if "free_cancel_deadline" not in cols:
        op.add_column(
            _TABLE,
            sa.Column("free_cancel_deadline", sa.Date(), nullable=True),
        )
        op.create_index("ix_trip_bookings_free_cancel_deadline", _TABLE, ["free_cancel_deadline"])


def downgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    if "free_cancel_deadline" in cols:
        op.drop_index("ix_trip_bookings_free_cancel_deadline", table_name=_TABLE)
        op.drop_column(_TABLE, "free_cancel_deadline")