"""地图拖拽修订 Schemas：POST /trips/{trip_id}/map-edit 请求/响应。

设计原则（docs/articles/05-map-edit-paradigms.md §4/§5「统一 diff 内核」）：
- 拖拽只产生最小结构：目标站点 name + 新坐标（lat/lng），与 AI 修订的
  ReviseDiff(op=replace, fields={lat,lng}) 同构，走同一条原子应用管线；
- 坐标是外部输入 → Pydantic 强范围校验（lat∈[-90,90]、lng∈[-180,180]），
  非法坐标 422 拒绝，绝不进入 diff；
- day_number 可空：缺省时由服务层按 name 在全行程中定位（第一个匹配），
  兼容前端 markers 未携带 day_number 的场景。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MapEditRequest(BaseModel):
    """一次地图拖拽修订：把某站点移动到新坐标。"""

    name: str = Field(min_length=1, max_length=200, description="站点名称（定位目标，与 revise target.name 同语义）")
    lat: float = Field(ge=-90, le=90, description="新纬度（范围外 → 422，绝不落库）")
    lng: float = Field(ge=-180, le=180, description="新经度（范围外 → 422，绝不落库）")
    day_number: int | None = Field(default=None, ge=1, description="可选：站点所在天；缺省按 name 全行程定位")


class MapEditOut(BaseModel):
    """地图拖拽修订结果：与新行程 plan 快照同构（前端详情页主数据来自 trip 本身）。"""

    applied: bool = True
    summary: str
    plan: dict
    diff: list[dict] = Field(default_factory=list, description="人类可读动作描述（同 revise 响应）")
    driving: dict = Field(default_factory=dict, description="修订后的自驾报告（DrivingGate 重算）")