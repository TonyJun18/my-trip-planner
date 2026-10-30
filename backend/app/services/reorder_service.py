"""行程重排提交服务（task-floattrip-borrow Story 1：拖拽换序 + 撤销/重做 + 保存重算）。

设计（与 map_edit_service 同哲学，共用 diff 内核与预算重算管线）：
- 前端拖拽是在本地草稿操作（未保存不落库 → 撤销/重做随草稿），只有点「保存」
  才把整日站点顺序快照提交到后端；
- 本服务校验每个 day_id 属于该 trip，且 order 必须包含该日全部站点 id
  （乱序/缺漏 → 400，绝不静默裁剪）；
- DrivingGate 前置：重排后若产生超距/超时 → 整体拒绝 400（前端提示），
  与地图拖拽同一条约束门；
- 预算重算 + 自驾报告回填复用 revise_service._recompute_budget（含版本保留）；
- 落库独立小事务：flush → recompute → commit；失败回滚不留半截。

安全边界：
- 外部输入校验：order 必须精确匹配站点 id 集合（防注入/防缺漏）；
- 只允许改顺序（order_index），绝不接受 name/cost/坐标等字段（最小指令）；
- 仅 owner 可改（与 revise/map_edit 同鉴权）；受邀编辑版不做（Story 1 范围）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models import Stop, Trip
from app.services import revise_service as _rs
from app.services._common import TRIP_LOADS
from app.services.driving_service import check_plan_driving_async


async def commit_reorder(
    db: AsyncSession,
    trip_id: str,
    *,
    days: list[dict[str, Any]],
    owner: str | None = None,
) -> dict[str, Any]:
    """提交一次多日重排（原子落库 + DrivingGate 前置 + 预算重算）。

    ``days``: [{day_id, order: [stop_id, ...]}]——order 必须包含该日全部站点。
    失败抛 AppError（400，前端提示）；成功返回 {summary, plan, driving}。
    """
    if not days:
        raise AppError("重排指令为空", code="reorder_empty")

    trip = await _rs._load_trip(db, trip_id, owner=owner)
    day_map = {d.id: d for d in trip.days}

    # 1) 校验所有 day_id 属于该 trip，且 order 精确匹配该日站点 id 集合
    for item in days:
        day_id = item.get("day_id") or ""
        day = day_map.get(day_id)
        if day is None:
            raise NotFoundError("日程不存在或不属于该行程", code="reorder_day_not_found")
        stop_ids = {s.id for s in day.stops}
        order = item.get("order") or []
        if len(order) != len(stop_ids) or set(order) != stop_ids:
            raise AppError("顺序列表必须包含该日全部站点", code="stop_order_invalid")

    # 2) 原子应用：只改 order_index（执行顺序与校验分离，全部校验通过才动手）
    for item in days:
        day_id = item.get("day_id") or ""
        day = day_map[day_id]
        by_id = {s.id: s for s in day.stops}
        for idx, stop_id in enumerate(item["order"], start=1):
            by_id[stop_id].order_index = idx

    # 3) DrivingGate 前置（重排后站点组合可能超距/超时）→ 整体拒绝
    await _rs._enforce_driving_constraints(trip)

    # 4) 落库独立小事务：flush → 预算重算（含版本保留）→ commit
    await db.flush()
    await _rs._recompute_budget(db, trip)
    await db.commit()

    # 5) 终态快照（commit 后 ORM 属性过期，重新加载保证新鲜）
    stmt = select(Trip).options(*TRIP_LOADS).where(Trip.id == trip_id)
    final_trip = (await db.execute(stmt)).scalar_one_or_none()
    if final_trip is None:
        raise NotFoundError("行程不存在", code="trip_not_found")
    plan = _rs._plan_snapshot(final_trip)
    driving = await check_plan_driving_async(plan)

    return {
        "applied": True,
        "summary": f"已保存重排（{len(days)} 天 · {sum(len(d.get('order') or []) for d in days)} 站）",
        "plan": plan,
        "driving": driving,
    }