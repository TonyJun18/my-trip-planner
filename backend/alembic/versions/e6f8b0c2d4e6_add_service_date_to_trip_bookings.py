"""预订台账：trip_bookings 增 service_date / service_note

Revision ID: e6f8b0c2d4e6
Revises: d4e6f8a0b2c4
Create Date: 2026-11-11 12:00:00.000000

task-booking-ledger-rhythm（方案一·订单台账）：
- service_date：服务日期（车次发车日 / 酒店入住日 / 门票出行日），台账排序
  与倒计时键，可空不参与状态机；
- service_note：用户自由文本备注（车次 / 房型 / 取消政策），零结构化承诺。
两者均可空：存量行零回填，可 downgrade。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6f8b0c2d4e6"
down_revision: str | None = "d4e6f8a0b2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "trip_bookings"


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    if "service_date" not in cols:
        op.add_column(
            _TABLE,
            sa.Column("service_date", sa.Date(), nullable=True),
        )
        op.create_index("ix_trip_bookings_service_date", _TABLE, ["service_date"])
    if "service_note" not in cols:
        op.add_column(
            _TABLE,
            sa.Column("service_note", sa.String(length=500), nullable=True),
        )


def downgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    if "service_note" in cols:
        op.drop_column(_TABLE, "service_note")
    if "service_date" in cols:
        op.drop_index("ix_trip_bookings_service_date", table_name=_TABLE)
        op.drop_column(_TABLE, "service_date")
