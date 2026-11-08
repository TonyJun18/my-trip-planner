"""单日站点顺序优化（task-auto-optimize-cta：「按最优顺序重排」一键入口）。

设计哲学（与 time_validation / solver_service 同源：确定性、可单测、零 LLM）：

- **首站锚定**：当天第一站不动——起点通常由住宿/交通决定，工具不该悄悄改掉用户
  的出发点；只重排「从第一站出发后」的访问顺序。
- **最近邻**（greedy nearest neighbour，球面距离）：站点少、约束简单，贪心足够，
  也比「LLM 排序」可解释、可复现。
- **只在真变短时提议**：省不到 ``MIN_GAIN_RATIO``（1%）就回 ``already_optimal``，
  不做无意义的重排，也不假装「优化过了」。
- **缺坐标不硬塞**：没有经纬度的站点保持原槽位，只让有坐标的站点参与排队；
  有坐标的站点不足 ``MIN_STOPS`` 时直接判 ``insufficient_coords``。
- **落库复用既有管线**：``reorder_service.commit_reorder`` 负责校验 + 原子落库 +
  DrivingGate 前置 + 预算重算（含版本保留）——本模块**不放宽任何约束**，自驾/时间
  门不通过时错误原样上抛给前端。
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.services import reorder_service
from app.services import revise_service as _rs

EARTH_RADIUS_KM = 6371.0
# 少于 3 站的重排没有意义（2 站的顺序差异几乎总是「首站锚定」已决定）
MIN_STOPS = 3
# 至少省 1% 才建议变更，避免来回抖动
MIN_GAIN_RATIO = 0.01


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """球面距离（km）：确定性估算，与 DrivingGate 同口径思路（不等导航里程）。"""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _path_km(points: list[tuple[float, float]]) -> float:
    return sum(_haversine_km(points[i], points[i + 1]) for i in range(len(points) - 1))


def _coords(stop: dict[str, Any]) -> tuple[float, float] | None:
    lat, lng = stop.get("lat"), stop.get("lng")
    if lat is None or lng is None:
        return None
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def _nearest_neighbour(anchor: tuple[float, float], rest: list[tuple[str, tuple[float, float]]]) -> list[str]:
    """从 anchor 出发的确定性最近邻；距离相同按 id 排序保证结果稳定。"""
    unvisited = sorted(rest, key=lambda item: item[0])
    current = anchor
    order: list[str] = []
    while unvisited:
        best = min(unvisited, key=lambda item: (_haversine_km(current, item[1]), item[0]))
        order.append(best[0])
        current = best[1]
        unvisited.remove(best)
    return order


def optimize_order(stops: list[dict[str, Any]]) -> dict[str, Any]:
    """纯函数：给一天的站点算一个更短的顺序。

    ``stops``: [{id, name, lat, lng, order_index}]（任意顺序传入，内部按 order_index 排）。
    返回 ``{changed, reason, order, names, distance_before_km, distance_after_km, saved_km}``；
    ``changed=False`` 时 ``order`` 仍返回当前顺序（调用方据此决定是否落库）。
    """
    ordered = sorted(stops, key=lambda s: (s.get("order_index") or 0, s.get("id") or ""))
    current_ids = [str(s.get("id") or "") for s in ordered]
    base = {
        "order": current_ids,
        "names": [s.get("name") or "" for s in ordered],
        "distance_before_km": 0.0,
        "distance_after_km": 0.0,
        "saved_km": 0.0,
    }

    if len(ordered) < MIN_STOPS:
        return {**base, "changed": False, "reason": "too_few_stops"}

    located: list[tuple[str, tuple[float, float]]] = []
    for s in ordered:
        sid = s.get("id")
        coord = _coords(s)
        if sid and coord is not None:
            located.append((str(sid), coord))
    if len(located) < MIN_STOPS:
        return {**base, "changed": False, "reason": "insufficient_coords"}

    # 首站锚定：当前顺序里第一个有坐标的站点保持不动
    anchor_id, anchor_coord = located[0]
    rest = located[1:]
    new_located_order = [anchor_id] + _nearest_neighbour(anchor_coord, rest)

    # 缺坐标的站点保持原槽位：把「有坐标的位置」按新顺序依次填充
    located_ids = {sid for sid, _ in located}
    queue = list(new_located_order)
    new_ids: list[str] = []
    for sid in current_ids:
        new_ids.append(queue.pop(0) if sid in located_ids else str(sid))

    before_coords = [coord for _, coord in located]
    by_id = {sid: coord for sid, coord in located}
    after_coords = [by_id[sid] for sid in new_ids if sid in by_id]
    before_km = _path_km(before_coords)
    after_km = _path_km(after_coords)
    saved = max(0.0, before_km - after_km)

    changed = new_ids != current_ids and before_km > 0 and saved / before_km >= MIN_GAIN_RATIO
    name_by_id = {s.get("id"): s.get("name") or "" for s in ordered}
    return {
        "order": new_ids if changed else current_ids,
        "names": [name_by_id.get(sid, "") for sid in (new_ids if changed else current_ids)],
        "distance_before_km": round(before_km, 2),
        "distance_after_km": round(after_km if changed else before_km, 2),
        "saved_km": round(saved if changed else 0.0, 2),
        "changed": changed,
        "reason": "reordered" if changed else "already_optimal",
    }


async def optimize_day_order(
    db: AsyncSession,
    trip_id: str,
    day_id: str,
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    """优化某一天的访问顺序；真正更短时走 ``commit_reorder`` 原子落库。

    返回 ``{changed, reason, day_id, day_number, order, names, distance_before_km,
    distance_after_km, saved_km}``；需要落库时额外带上 ``summary/plan/driving``。
    """
    trip = await _rs._load_trip(db, trip_id, owner=owner)
    day = next((d for d in trip.days if d.id == day_id), None)
    if day is None:
        raise NotFoundError("日程不存在或不属于该行程", code="optimize_day_not_found")

    stops = [
        {
            "id": s.id,
            "name": s.name,
            "lat": s.lat,
            "lng": s.lng,
            "order_index": s.order_index,
        }
        for s in day.stops
    ]
    proposal = optimize_order(stops)
    result: dict[str, Any] = {
        "day_id": day.id,
        "day_number": day.day_number,
        **proposal,
    }
    if not proposal["changed"]:
        return result

    # 原子落库：DrivingGate 前置 + 预算重算（约束不通过时原样抛 400 给前端）
    applied = await reorder_service.commit_reorder(
        db, trip_id, days=[{"day_id": day.id, "order": proposal["order"]}], owner=owner,
    )
    result.update({
        "summary": applied["summary"],
        "plan": applied["plan"],
        "driving": applied.get("driving") or {},
    })
    return result
