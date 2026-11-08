"""行程拖拽重排提交 Schemas（task-floattrip-borrow Story 1：拖拽换序 + 保存重算）。

与 map_edit（地图拖拽）同哲学：前端直接操作 → 结构化的最小指令 → 服务端
原子应用。区别在于本指令是一次「整日站点顺序快照」（含多日批量），服务端
校验后原子落库 + DrivingGate 前置 + 预算重算，失败整体回滚，不产生半保存。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReorderDayIn(BaseModel):
    """一日重排指令：order 必须包含该日全部站点 id（乱序/缺漏 → 400）。"""

    day_id: str = Field(min_length=1, description="日程 id")
    order: list[str] = Field(min_length=1, description="该日全部站点 id 的新顺序（从前到后）")


class ReorderCommitIn(BaseModel):
    """一次拖拽会话的保存指令：多日批量重排（前端草稿只保存已改动的天）。"""

    days: list[ReorderDayIn] = Field(
        min_length=1, max_length=30, description="多日重排（每项必须含该日全部站点）"
    )


class ReorderCommitOut(BaseModel):
    """重排提交结果：与新行程 plan 快照同构（前端详情页主数据来自 trip 本身）。"""

    applied: bool = True
    summary: str
    plan: dict
    driving: dict = Field(default_factory=dict, description="重排后的自驾报告（DrivingGate 重算）")


class OptimizeOrderOut(BaseModel):
    """单日「按最优顺序重排」结果（task-auto-optimize-cta）。

    ``changed=False`` 时没落库（``already_optimal`` / ``too_few_stops`` /
    ``insufficient_coords``），前端只提示不刷新；``changed=True`` 时顺序已原子落库，
    附带 summary/plan/driving 供前端刷新与提示。
    """

    changed: bool
    reason: str = Field(description="reordered / already_optimal / too_few_stops / insufficient_coords")
    day_id: str
    day_number: int
    order: list[str] = Field(description="该日站点新顺序（未变更时为当前顺序）")
    names: list[str] = Field(default_factory=list, description="与新顺序对应的站点名（前端展示用）")
    distance_before_km: float = 0.0
    distance_after_km: float = 0.0
    saved_km: float = 0.0
    # 仅在 changed=True 时出现（复用 reorder_commit 的产出）
    summary: str | None = None
    plan: dict | None = None
    driving: dict | None = None