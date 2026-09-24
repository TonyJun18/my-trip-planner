"""merge google auth and collab heads

Revision ID: d71385961648
Revises: c35e3c0ec0fb, e5302ddbcdd2
Create Date: 2026-09-23 21:29:40.917919
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'd71385961648'
down_revision: str | None = ('c35e3c0ec0fb', 'e5302ddbcdd2')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass