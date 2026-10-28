"""行中费用分摊 Schemas（task-expense-split-mini）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExpenseIn(BaseModel):
    """新增一条费用记录（金额/类别/支付人/备注）。"""

    category: Literal["food", "transport", "hotel", "attraction", "shopping", "other"] = "other"
    amount: float = Field(gt=0, description="实际花费金额（元，>0）")
    payer: str = Field(default="", max_length=50, description="支付人姓名（自由文本；空串=未指定）")
    note: str | None = Field(default=None, max_length=200, description="备注（≤200 字）")


class ExpenseOut(BaseModel):
    """一条费用记录（响应）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    category: str
    amount: float
    payer: str
    note: str | None = None
    created_at: datetime


class ExpenseBalanceOut(BaseModel):
    """费用分摊汇总：总额 + 人均结余。

    - ``total``：全部记录金额合计（含未指定支付人的记录）；
    - ``per_person``：指定了支付人的记录，按支付人聚合 ÷ 行程人数（travelers）得出
      人均应摊；结余 = 支付人已付 - 人均应摊（正=别人欠他，负=他欠别人）；
    - ``unassigned``：payer 为空串的记录金额合计（不参与分摊，仅计入 total）。
    """

    trip_id: str
    travelers: int
    total: float = 0.0
    per_person: float = 0.0
    balances: dict[str, float] = Field(default_factory=dict)  # payer → 结余
    unassigned: float = 0.0
    count: int = 0