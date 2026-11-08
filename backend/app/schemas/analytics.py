"""前端埋点事件 Schemas（task-trip-detail-refactor：意图/曝光基线，不落库）。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 事件名白名单（与前端 src/api/modules/analytics.js 的 ANALYTICS_EVENTS 保持一致）
AnalyticsEventName = Literal[
    "planning_tool_open",  # 规划工具打开（AI修订/PlanB/质检/批量生成）→ G1
    "top_action_click",  # 顶栏主操作（编辑/问AI/分享） → G5
    "itinerary_first_view",  # 逐日行程首屏是否可见 → G2
    "itinerary_scroll_depth",  # 滚动深度 25/50/75% → G2
    # 收纳层信号（阶段二收口）：区分「没进工具区」与「进了但 tab 迷路 / 逃到全部工具」两种 G1 失败形态
    "workspace_tab_switch",  # 工作台 tab 切换 → G1（带 from→to）
    "workspace_all_toggle",  # 「全部工具」开关 → G1（逃生通道使用频次）
]

# 规划工具白名单
PlanningTool = Literal["ai_revise", "plan_b", "qa", "batch_gen"]
# 顶栏主操作白名单
TopAction = Literal["edit", "ask_ai", "share"]
# 滚动深度白名单
Depth = Literal[25, 50, 75]
# 工作台 tab 白名单（all = 「全部工具」态，作为 from 出现时表示从逃生通道切回）
WorkspaceTab = Literal["plan", "prep", "live", "review", "all"]


class AnalyticsEventPayload(BaseModel):
    """事件载荷（公共字段 + 专有字段宽松共存）。"""

    # 公共载荷（前端自动附加）
    trip_id: str | None = None
    trip_phase: Literal["planning", "live", "finished"] | None = None
    viewport_width: int | None = Field(default=None, ge=0, le=10000)
    is_touch: bool | None = None
    role: Literal["owner", "guest"] | None = None

    # 专有载荷（按事件名区分）
    tool: PlanningTool | None = None
    action: TopAction | None = None
    visible: bool | None = None
    depth: Depth | None = None
    # 收纳层信号（workspace_tab_switch / workspace_all_toggle）
    tab: WorkspaceTab | None = None
    from_tab: WorkspaceTab | None = Field(default=None, alias="from")
    on: bool | None = None


class AnalyticsEventIn(BaseModel):
    """POST /analytics/events 请求体。"""

    name: AnalyticsEventName
    payload: AnalyticsEventPayload = AnalyticsEventPayload()