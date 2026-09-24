"""行程备选方案（Plan B）Schema：请求/响应的 Pydantic 模型。

独立成模块（不并入 schemas/__init__.py），避免与用户未提交的
schemas/__init__.py 改动混淆；API 层直接从这里 import。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# 备选方案描述的最大长度（deltas 列表最长 20 条）
_MAX_DELTAS = 20
_MAX_DELTA_LEN = 200


class PlanBVariantOut(BaseModel):
    """一个备选方案变体（骨架 + 与主案的差异说明）。"""

    label: str = Field(description="变体名字，如「节奏优化版」")
    description: str = Field(description="变体的一句话说明")
    deltas: list[str] = Field(default_factory=list, max_length=_MAX_DELTAS, description="与主案的差异点列表（供前端对比展示）")
    days: list = Field(default_factory=list, description="备选骨架天数（与 TripPlan.plan_data.days 同构）")
    budget: dict = Field(default_factory=dict, description="备选骨架预算汇总（total_estimated/by_type/currency）")


class PlanBOut(BaseModel):
    """GET /trips/{trip_id}/plan-b 的响应。"""

    trip_id: str
    variant: PlanBVariantOut | None = Field(default=None, description="备选方案；行程无站点时为 None（前端隐藏入口）")
    note: str = Field(default="", description="提示文案（如无站点时的说明）")