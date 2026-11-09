"""add multi-currency fields to trip_expenses (task-multi-currency-expense-eval)

Revision ID: a4b5c6d7e8f9
Revises: f2a3b4c5d6e7
Create Date: 2026-11-09 03:20:00.000000

task-multi-currency-expense-eval：费用记录多币种（录入时锁定汇率，零凭证）。
- trip_expenses.currency：记账原币种（ISO 4217，默认 CNY）。
- trip_expenses.rate_to_base：录入时锁定的「1 原币 = ? 基准币(CNY)」汇率（默认 1.0）。
- trip_expenses.amount_base：按锁定汇率折算出的基准金额（默认 = amount）。

旧数据兼容：三列均有默认值（CNY / 1.0 / amount 回填），存量记录自动视为 CNY，
行为不变；使用同表 amount 值回填 amount_base。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a4b5c6d7e8f9'
down_revision: str | None = 'f2a3b4c5d6e7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 防御式幂等：create_all 可能已建列（项目哲学：先查后改）
    bind = op.get_bind()
    cols = [c["name"] for c in bind.dialect.get_columns(bind, "trip_expenses")]
    if "currency" not in cols:
        op.add_column('trip_expenses', sa.Column('currency', sa.String(length=10), nullable=False, server_default='CNY'))
    if "rate_to_base" not in cols:
        op.add_column('trip_expenses', sa.Column('rate_to_base', sa.Float(), nullable=False, server_default='1.0'))
    if "amount_base" not in cols:
        # 存量记录回填 = amount×1.0 = amount（旧记录视为 CNY）
        op.add_column('trip_expenses', sa.Column('amount_base', sa.Float(), nullable=True))
        op.execute("UPDATE trip_expenses SET amount_base = amount WHERE amount_base IS NULL")
        op.alter_column('trip_expenses', 'amount_base', nullable=False)


def downgrade() -> None:
    op.drop_column('trip_expenses', 'amount_base')
    op.drop_column('trip_expenses', 'rate_to_base')
    op.drop_column('trip_expenses', 'currency')