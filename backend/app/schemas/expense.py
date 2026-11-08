"""行中费用分摊 Schemas（task-expense-split-mini）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExpenseIn(BaseModel):
    """新增一条费用记录（金额/币种/类别/支付人/备注）。

    - ``currency``：记账原币种（ISO 4217，默认 CNY）。CNY 时无需汇率；
      非 CNY 时可用 ``rate_to_base`` 显式给「1 原币 = ? 基准币(CNY)」，否则查规则库兜底；
      规则库无此币种且未给汇率 → 422 明确提示（诚实口径：不编造汇率）。
    - ``rate_to_base``：可选。录入时锁定的折算汇率（append-only，锁后不可变）。
    """

    category: Literal["food", "transport", "hotel", "attraction", "shopping", "other"] = "other"
    amount: float = Field(gt=0, description="实际花费原币金额（>0）")
    currency: str = Field(default="CNY", min_length=3, max_length=10, description="记账原币种（ISO 4217，默认 CNY）")
    rate_to_base: float | None = Field(default=None, gt=0, description="可选：1 原币 = ? 基准币（CNY）；锁后不可变")
    payer: str = Field(default="", max_length=50, description="支付人姓名（自由文本；空串=未指定）")
    note: str | None = Field(default=None, max_length=200, description="备注（≤200 字）")


class ExpenseOut(BaseModel):
    """一条费用记录（响应）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    category: str
    amount: float
    amount_base: float
    currency: str
    rate_to_base: float
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
    currencies: list[str] = Field(default_factory=list)  # 出现过的原币种（信息透出）