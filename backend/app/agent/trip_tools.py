"""对话助手行程感知工具（方案 1：只读打通）。

设计文档：``docs/chat-trip-data-flow-design.md``（2026-10-28，方案 1 + 2）。

解决的问题：对话式行程助手（B 期 chat）原本是「通用导游」——工具集只有
外部数据源（search_attractions / search_hotels / ...），完全读不到用户
自己的行程。本模块把用户行程数据以**摘要契约**暴露给 AgentLoop：

- ``get_my_trips``：当前用户的行程列表（标题/目的地/日期/状态）
- ``get_trip_overview``：单个行程的定位摘要（days/stops + 预算 + 最新方案索引）

设计要点：
- **只读**：不提供任何写工具；写路径见 ``trip_edit_tool.py``（方案 2）。
- **owner 隔离**：所有查询走 ``trip_service._load_trip(owner=user_id)``，
  用户只能读到自己的行程；跨用户 → 结构化错误（LLM 如实告知，不编造）。
- **摘要契约而非全量 plan JSON**：``TripPlan.plan_data`` 动辄 5-10k tokens，
  整段塞进对话会把上下文预算打爆。工具只返回定位所需的最小字段
  （day_number / name / type / 关键元数据），并带 ``truncated`` 显式标记。
- **数据来源优先级**（与 skill「checkin-hotel-bug」教训一致）：
  1. ``TripPlan.plan_data``（最新快照）中的 ``days[].stops[]`` —— 已安排站点；
  2. 快照缺失 → ORM ``trip.days[].stops[]`` 原始数据；
  3. 都没有 → 明确返回「暂无站点数据」，**绝不返回 plan.hotels 候选池冒充已安排住宿**。
- ``execute`` 通过闭包持有 ``db`` 与 ``owner``，不在工具参数里信任 LLM 传的
  trip_id（会话绑定值优先；LLM 传入的 trip_id 也必须做 owner 校验）。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.runtime import AgentTool
from app.core.logging import get_logger
from app.models import Trip, TripDay, Stop

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════
#  参数模型（AgentTool.parameters → JSON schema → 强校验）
# ═══════════════════════════════════════════════════════════
class TripIdParams(BaseModel):
    """get_trip_overview 参数：trip_id 可选，缺省用会话绑定值。"""

    trip_id: str | None = Field(default=None, description="行程 ID；缺省使用会话绑定的行程")


# 摘要契约的截断阈值（防上下文爆炸，显式标记不静默截断）
_MAX_OVERVIEW_STOPS = 12          # 单日最多展开的站点数
_MAX_OVERVIEW_DAYS = 7            # 最多展开的天数（超出折叠为 summary）
_STOP_HOTEL_TYPE = "hotel"
_STOP_FOOD_TYPE = "food"
_STOP_ATTRACTION_TYPE = "attraction"


# ═══════════════════════════════════════════════════════════
#  摘要组装（纯函数，方便单测）
# ═══════════════════════════════════════════════════════════
def _stop_summary(stop: Stop) -> dict[str, Any]:
    """单个站点的摘要字段（定位所需最小集）。"""
    return {
        "name": stop.name,
        "type": stop.stop_type,
        "lat": stop.lat,
        "lng": stop.lng,
        "estimated_cost": float(stop.estimated_cost or 0),
        "duration_minutes": stop.estimated_duration_minutes,
    }


def _day_summary(day: TripDay) -> dict[str, Any]:
    """一天的摘要：day_number/date/theme + 站点列表（截断带标记）。"""
    stops = sorted(day.stops, key=lambda s: s.order_index)
    truncated = len(stops) > _MAX_OVERVIEW_STOPS
    return {
        "day_number": day.day_number,
        "date": day.date.isoformat() if day.date else None,
        "theme": day.note,
        "stops": [_stop_summary(s) for s in stops[:_MAX_OVERVIEW_STOPS]],
        "truncated": truncated,
    }


def _trip_overview_from_days(trip: Trip, days: list[TripDay]) -> dict[str, Any]:
    """从 days（已按 day_number 展开）组装行程摘要。"""
    days_sorted = sorted(days, key=lambda d: d.day_number)
    days_truncated = len(days_sorted) > _MAX_OVERVIEW_DAYS
    day_list = [_day_summary(d) for d in days_sorted[:_MAX_OVERVIEW_DAYS]]
    if days_truncated:
        day_list.append({
            "day_number": None,
            "date": None,
            "theme": f"… 共 {len(days_sorted)} 天，已折叠超出部分",
            "stops": [],
            "truncated": False,
        })
    return {
        "days": day_list,
        "days_truncated": days_truncated,
        "stop_count": sum(len(d.stops) for d in days_sorted),
    }


def _trip_overview_dict(trip: Trip, days: list[TripDay], *, has_plan_snapshot: bool, budget: dict[str, Any]) -> dict[str, Any]:
    """完整的行程摘要 dict（供工具返回）。

    budget 由调用方从 TripPlan.plan_data 读取（快照预算可能缺失 → 默认空）；
    不能从 ``revise_service._plan_snapshot`` 取——该函数预算硬编码为 0.0。
    """
    days_part = _trip_overview_from_days(trip, days)
    out: dict[str, Any] = {
        "trip_id": trip.id,
        "title": trip.title,
        "destination": trip.destination,
        "departure": trip.departure,
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "travelers": trip.travelers,
        "status": trip.status,
        "updated_at": trip.updated_at.isoformat() if trip.updated_at else None,
        "has_plan_snapshot": has_plan_snapshot,
        "days": days_part["days"],
        "days_truncated": days_part["days_truncated"],
        "stop_count": days_part["stop_count"],
        "budget": budget,
    }
    return out


# ═══════════════════════════════════════════════════════════
#  工具工厂（闭包注入 db / owner，不信任 LLM 传参）
# ═══════════════════════════════════════════════════════════
async def _get_my_trips(db, owner: str | None) -> str:
    """查询当前用户的行程列表（压缩摘要）。"""
    from app.services import trip_service

    trips, _ = await trip_service.list_trips(db, owner=owner, limit=20)
    items = [
        {
            "trip_id": t.id,
            "title": t.title,
            "destination": t.destination,
            "start_date": t.start_date.isoformat() if t.start_date else None,
            "end_date": t.end_date.isoformat() if t.end_date else None,
            "status": t.status,
            "travelers": t.travelers,
        }
        for t in trips
    ]
    return _json_dumps({"count": len(items), "items": items})


async def _get_trip_overview(db, owner: str | None, trip_id: str | None) -> str:
    """查询单个行程的定位摘要（owner 隔离）。"""
    from app.services import trip_service

    if not trip_id:
        return _json_dumps({"error": "missing_trip_id", "detail": "未提供行程 ID，请先绑定或调用 get_my_trips"})
    try:
        trip = await trip_service._load_trip(db, trip_id, owner=owner)
    except Exception as exc:  # noqa: BLE001 — 结构性失败：行程不存在/无权限
        return _json_dumps({
            "error": "trip_not_found",
            "detail": f"行程不存在或无权限访问（{exc}）",
        })
    plan = await trip_service.get_plan_by_trip_id(db, trip.id)
    has_snapshot = plan is not None and bool((plan.plan_data or {}).get("days"))
    # 预算从快照读取（快照缺失/无预算 → 默认空结构；不阻断读取）
    plan_budget = {}
    if plan is not None:
        plan_budget = (plan.plan_data or {}).get("budget") or {}
    budget = {
        "total_estimated": float(plan_budget.get("total_estimated") or 0.0),
        "by_type": plan_budget.get("by_type") or {},
        "currency": plan_budget.get("currency") or "CNY",
    }
    # 站点统一以 ORM days/stops 为准（快照只提供预算/quality 等元数据；
    # 与 revise 快照语义一致，避免快照缺字段导致站点信息不齐）
    days = trip.days

    return _json_dumps(_trip_overview_dict(trip, days, has_plan_snapshot=has_snapshot, budget=budget))


def _json_dumps(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)


def make_trip_tools(*, db, owner: str | None, trip_id: str | None = None) -> list[AgentTool]:
    """构造当前用户可用的行程感知工具（只读）。

    trip_id 为会话绑定行程：get_trip_overview 缺省参数时优先使用绑定值；
    用户显式传入其他 trip_id 也允许（只要属于该 owner），但绑定值优先防串台。
    """
    bound_trip_id = trip_id

    async def _overview(trip_id: str | None = None) -> str:
        effective = trip_id or bound_trip_id
        return await _get_trip_overview(db, owner, effective)

    async def _list_trips(**_kwargs: Any) -> str:
        """无参数工具：兼容 AgentLoop 以 **args 调用 execute。"""
        return await _get_my_trips(db, owner)

    return [
        AgentTool(
            name="get_my_trips",
            description=(
                "查询当前登录用户自己的行程列表（标题、目的地、日期、状态）。"
                "当用户提到『我的行程』『我的计划』且没有明确 trip_id 时使用。"
                "返回结构化 JSON；无行程时返回空列表。"
            ),
            execute=_list_trips,
            parameters=None,  # 无参数
            retryable=True,
        ),
        AgentTool(
            name="get_trip_overview",
            description=(
                "查询某个行程的定位摘要（天数、每日站点、预算、状态）。"
                "参数 trip_id 缺省时使用会话绑定的行程；若未绑定且未传 trip_id，返回错误提示。"
                "数据来自用户自己的行程，owner 隔离。"
            ),
            execute=_overview,
            parameters=TripIdParams,
            retryable=True,
        ),
    ]