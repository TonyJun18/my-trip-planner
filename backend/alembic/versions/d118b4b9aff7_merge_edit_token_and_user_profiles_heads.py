"""merge edit_token and user_profiles heads

Revision ID: d118b4b9aff7
Revises: a1f2b3c4d5e6, e8c5a9ad4e68
Create Date: 2026-09-24 22:05:32.551117
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'd118b4b9aff7'
down_revision: str | None = ('a1f2b3c4d5e6', 'e8c5a9ad4e68')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass