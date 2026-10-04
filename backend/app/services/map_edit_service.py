"""地图拖拽修订服务：把「拖动 marker 改坐标」转成最小 ReviseDiff 并原子应用。

设计（docs/articles/05-map-edit-paradigms.md §4/§5「统一 diff 内核」）：
- 拖拽只产生 {name, lat, lng} → 构造 op=replace 的 ReviseDiff（fields={lat,lng}），
  与 AI 修订走**同一条** _apply_diff 原子预检 + 执行管线——手动拖拽与 LLM 修订
  共用一个 diff 内核，校验规则天然一致；
- 自驾约束门（DrivingGate）前置校验：拖拽后若产生超距/超时站点组合 → 整体
  拒绝并返回 detail.issues（前端弹出「自驾约束提醒」，绝不静默落库）；
- 预算重算复用 revise_service._recompute_budget（坐标变化 → 大交通/酒店估算联动）；
- 落库独立小事务：flush → recompute → commit；失败回滚不留半截。

安全边界：
- 坐标是外部输入：Pydantic 范围校验在前（422），本服务兜底再校验一次；
- 只允许 replace lat/lng：拖拽语义最小化，绝不接受 name/description/cost 等字段；
- 站点定位宽松（先 day_number+name，再全行程按 name），找不到 → 404，
  明确报错而不是静默 no-op。
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import AppError, NotFoundError
from app.services import revise_service as _rs
from app.services.driving_service import check_plan_driving_async


async def map_edit_trip(
    db: Any,
    trip_id: str,
    *,
    name: str,
    lat: float,
    lng: float,
    day_number: int | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """执行一次地图拖拽修订，返回 {applied, summary, plan, diff, driving}。"""
    # 0) 坐标兜底校验（Pydantic 已在前置，这里防御 DB 直连等旁路）
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        raise AppError("坐标超出合法范围（lat∈[-90,90], lng∈[-180,180]）", code="map_edit_bad_coords")

    # 1) 定位站点（宽容：先按 day_number+name，再全行程按 name）
    trip = await _rs._load_trip(db, trip_id, owner=owner)
    matches: list[tuple[Any, Any]] = []
    for d in sorted(trip.days, key=lambda x: x.day_number):
        for s in d.stops:
            if s.name == name:
                matches.append((d, s))
    if not matches:
        raise NotFoundError(f"行程中找不到站点「{name}」", code="map_edit_stop_not_found")

    if day_number is not None:
        exact = [m for m in matches if m[0].day_number == day_number]
        if not exact:
            raise NotFoundError(
                f"第 {day_number} 天找不到站点「{name}」", code="map_edit_stop_not_found"
            )
        day, stop = exact[0]
    else:
        day, stop = matches[0]

    # 2) 无变化 no-op（拖回原位 → 不落库、不触发约束门）
    cur_lat = float(stop.lat or 0.0)
    cur_lng = float(stop.lng or 0.0)
    if abs(cur_lat - lat) < 1e-9 and abs(cur_lng - lng) < 1e-9:
        return {
            "applied": False,
            "summary": "坐标未变化",
            "plan": _rs._plan_snapshot(trip),
            "diff": [],
            "driving": {},
        }

    # 3) 构造最小 diff（op=replace，仅 lat/lng）→ 复用原子应用管线
    diff: dict[str, Any] = {
        "actions": [
            {
                "op": "replace",
                "day_number": day.day_number,
                "target": {"name": stop.name},
                "fields": {"lat": lat, "lng": lng},
            }
        ],
        "summary": f"地图调整「{stop.name}」位置",
    }
    try:
        _rs._apply_diff(trip, diff)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 — 统一转业务异常
        raise AppError(f"地图修订应用失败: {exc}", code="map_edit_apply_failed") from exc

    # 4) 自驾约束门（与 revise 同一条门：超距/超时 → 整体拒绝 400 + detail.issues）
    await _rs._enforce_driving_constraints(trip)

    # 5) 落库（独立小事务：主修订先 flush，预算重算后 commit）
    await db.flush()
    await _rs._recompute_budget(db, trip)
    await db.commit()

    # 6) 终态快照（重新加载保证 ORM 属性新鲜）+ 自驾报告注入
    final_trip = await _rs._load_trip(db, trip_id, owner=owner)
    plan = _rs._plan_snapshot(final_trip)
    driving = await check_plan_driving_async(plan)
    return {
        "applied": True,
        "summary": diff["summary"],
        "plan": plan,
        "diff": _rs._describe_actions(diff),
        "driving": driving,
    }