"""行程修订服务（方案 B：对话改行程）。

流程：
1. 读取行程当前状态（Trip / TripDay / Stop）
2. 调用 PlanReviseAgent：用户消息 + 当前行程 → 结构化 diff（ReviseDiff）
3. 编排层代码逐个应用 diff（AI 只出指令，代码执行）
4. 应用前校验（存在性 / 类型 / 位置），任一失败 → 整体回滚（原子性）
5. 落库后返回新行程 + 变更摘要

设计原则：
- AI 只做「理解 + 生成 diff」，不做任何直接修改——延续
  「LLM 只做理解，代码做执行」的项目哲学
- 原子性：diff 有任何一个动作非法 → 不落库任何变更（返回错误）
- 预算同步重算：改动站点后 budget 由代码重算（LLM 估值不可信）
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agents import plan_revise_agent
from app.core.exceptions import AppError
from app.models import Stop, Trip, TripDay, TripPlan
from app.services._common import TRIP_LOADS as _TRIP_LOADS
from app.services._common import normalize_trace as _normalize_trace


async def revise_trip(
    db: AsyncSession,
    trip_id: str,
    message: str,
    *,
    owner: str | None = None,
    provider: str = "auto",
) -> dict[str, Any]:
    """执行一次行程修订，返回 {plan, summary, trace, provider, model}。

    失败时抛 AppError（调用方转成 4xx 响应）。
    """
    trip = await _load_trip(db, trip_id, owner=owner)

    # 1) AI 生成 diff（无工具；失败可自纠正）
    current_plan = _plan_snapshot(trip)
    revise = await plan_revise_agent(
        {"message": message, "destination": trip.destination, "budget": trip.budget},
        current_plan,
        provider=provider,
    )
    if revise.get("status") != "completed" or revise.get("diff") is None:
        raise AppError(revise.get("error") or "AI 未能解析修改请求", code="revise_parse_failed")

    diff = revise["diff"]  # 已是校验过的干净 dict（ReviseDiff）

    # 2) 代码应用 diff（原子：先校验全部动作，再执行）
    try:
        _apply_diff(trip, diff)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(f"行程修订应用失败: {exc}", code="revise_apply_failed") from exc

    # 2.5) 自驾约束门（DrivingGate）：修订后站点组合超距/超时 → 整体拒绝
    _enforce_driving_constraints(trip)

    # 3) 落库 + 预算重算
    await db.flush()
    await _recompute_budget(db, trip)
    await db.commit()

    # 4) 组装响应（新 trip + plan 快照）
    new_plan = _plan_snapshot(trip)
    return {
        "trip_id": trip.id,
        "summary": diff.get("summary") or "行程已更新",
        "plan": new_plan,
        "diff": _describe_actions(diff),
        "trace": _normalize_trace(revise.get("trace") or []),
        "provider": revise.get("provider"),
        "model": revise.get("model"),
    }


# ── 内部：加载 / 快照 ──────────────────────────────────────
async def _load_trip(db: AsyncSession, trip_id: str, *, owner: str | None = None) -> Trip:
    from app.core.exceptions import NotFoundError

    stmt = select(Trip).options(*_TRIP_LOADS).where(Trip.id == trip_id)
    if owner is None:
        stmt = stmt.where(Trip.owner.is_(None))
    else:
        stmt = stmt.where(Trip.owner == owner)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("行程不存在", code="trip_not_found")
    return trip


def _plan_snapshot(trip: Trip) -> dict[str, Any]:
    """把 Trip（含 days/stops）序列化成与 TripPlan.plan_data 同构的 dict。"""
    days = []
    for day in sorted(trip.days, key=lambda d: d.day_number):
        stops = []
        for stop in sorted(day.stops, key=lambda s: s.order_index):
            stops.append({
                "name": stop.name,
                "type": stop.stop_type,
                "lat": stop.lat,
                "lng": stop.lng,
                "estimated_cost": float(stop.estimated_cost or 0),
                "duration_minutes": stop.estimated_duration_minutes,
                "description": stop.description,
            })
        days.append({
            "day_number": day.day_number,
            "date": day.date.isoformat() if day.date else None,
            "theme": day.note,
            "stops": stops,
        })
    return {
        "destination": trip.destination,
        "days": days,
        "budget": {"total_estimated": 0.0, "by_type": {}, "currency": "CNY"},
        "hotels": [],
        "warnings": [],
    }


# ── 内部：应用 diff（原子） ─────────────────────────────────
_OP_LABEL = {
    "replace": "修改",
    "add": "新增",
    "remove": "删除",
    "reorder": "调整顺序",
}


def _describe_actions(diff: dict[str, Any]) -> list[dict[str, Any]]:
    """把 AI 生成的 diff.actions 转成人类可读的预览列表（供前端展示）。

    每个动作保留结构化字段（op / day / 目标 / 新值），前端可用图标 + 文案渲染；
    不做任何落库副作用。
    """
    out: list[dict[str, Any]] = []
    for action in diff.get("actions") or []:
        op = action.get("op", "")
        day_number = action.get("day_number")
        target = action.get("target") or {}
        fields = action.get("fields") or {}
        name = target.get("name") or fields.get("name") or ""
        item: dict[str, Any] = {
            "op": op,
            "op_label": _OP_LABEL.get(op, op),
            "day_number": day_number,
            "target_name": name,
            "fields": fields,
        }
        if op == "reorder":
            item["index"] = action.get("index")
        out.append(item)
    return out


def _apply_diff(trip: Trip, diff: dict[str, Any]) -> None:
    """按顺序应用 diff 的所有动作。

    先做完整合法性检查（定位、类型、字段），全部通过后再写入，
    保证任一动作失败都不会产生部分修改（调用方捕获后抛错，由
    service 层保证不 commit —— 数据库事务即回滚）。
    """
    actions = diff.get("actions") or []

    # 预检：解析所有动作的目标（day / stop），提前失败
    resolved: list[tuple[dict[str, Any], TripDay, Stop | None]] = []
    for action in actions:
        day = _find_day(trip, action.get("day_number"))
        op = action.get("op")

        if op in ("replace", "remove", "reorder"):
            stop = _find_stop(day, action.get("target"))
            if stop is None:
                raise AppError(f"Day {action.get('day_number')} 找不到目标站点", code="revise_target_not_found")
        elif op == "add":
            stop = None
        else:
            raise AppError(f"不支持的变更操作: {op}", code="revise_bad_op")

        if op == "reorder":
            idx = action.get("index")
            if not idx or idx < 1 or idx > len(day.stops):
                raise AppError(f"Day {action.get('day_number')} 目标位置非法: {idx}", code="revise_bad_index")

        if op == "add":
            idx = action.get("index")
            if idx is not None and (idx < 1 or idx > len(day.stops) + 1):
                raise AppError(f"Day {action.get('day_number')} 插入位置非法: {idx}", code="revise_bad_index")

        resolved.append((action, day, stop))

    # 全部合法 → 实际执行
    for action, day, stop in resolved:
        op = action.get("op")
        ordered = _ordered_stops(day)
        if op == "replace":
            _replace_stop(stop, action.get("fields") or {})
        elif op == "remove":
            ordered.remove(stop)
            day.stops = ordered
            _renumber(day)
        elif op == "add":
            new_stop = _build_stop(day, action.get("fields") or {})
            idx = action.get("index")
            if idx:
                ordered.insert(idx - 1, new_stop)
            else:
                ordered.append(new_stop)
            day.stops = ordered
            _renumber(day)
        elif op == "reorder":
            ordered.remove(stop)
            ordered.insert(action.get("index", 1) - 1, stop)
            day.stops = ordered
            _renumber(day)


def _find_day(trip: Trip, day_number: Any) -> TripDay:
    day = next((d for d in trip.days if d.day_number == day_number), None)
    if day is None:
        raise AppError(f"行程中没有第 {day_number} 天", code="revise_day_not_found")
    return day


def _find_stop(day: TripDay, target: dict) -> Stop | None:
    if not isinstance(target, dict):
        return None
    name = target.get("name")
    index = target.get("index")
    if name:
        return next((s for s in day.stops if s.name == name), None)
    if index:
        idx = int(index)
        if 1 <= idx <= len(day.stops):
            return sorted(day.stops, key=lambda s: s.order_index)[idx - 1]
    return None


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """站点字段宽容归一化：容忍 LLM 输出别名（duration_minutes），映射为
    Stop 模型字段 estimated_duration_minutes；未知字段保持不变（由白名单把关）。"""
    out = dict(fields)
    if "duration_minutes" in out and "estimated_duration_minutes" not in out:
        out["estimated_duration_minutes"] = out.pop("duration_minutes")
    return out


def _replace_stop(stop: Stop, fields: dict[str, Any]) -> None:
    fields = _normalize_fields(fields)
    allowed = {"name", "stop_type", "lat", "lng", "description", "estimated_cost", "estimated_duration_minutes"}
    unknown = set(fields) - allowed
    if unknown:
        raise AppError(f"不支持的站点字段: {', '.join(sorted(unknown))}", code="revise_bad_field")
    for k, v in fields.items():
        if v is None:
            continue
        setattr(stop, k, v)


def _ordered_stops(day: TripDay) -> list[Stop]:
    """按 order_index 返回站点列表（新对象 order_index=0 排最后）。"""
    return sorted(day.stops, key=lambda s: (s.order_index is None, s.order_index or 0))


def _build_stop(day: TripDay, fields: dict[str, Any]) -> Stop:
    """根据字段构造一个尚未加入集合的新 Stop（order_index 占位 0）。"""
    fields = _normalize_fields(fields)
    if not fields.get("name"):
        raise AppError("新增站点缺少名称", code="revise_missing_name")
    allowed = {"name", "stop_type", "lat", "lng", "description", "estimated_cost", "estimated_duration_minutes"}
    unknown = set(fields) - allowed
    if unknown:
        raise AppError(f"不支持的站点字段: {', '.join(sorted(unknown))}", code="revise_bad_field")
    stop_type = fields.get("stop_type", "attraction")
    if stop_type not in ("attraction", "food", "hotel"):
        raise AppError(f"非法站点类型: {stop_type}", code="revise_bad_type")
    return Stop(
        day_id=day.id,
        name=fields.get("name"),
        stop_type=stop_type,
        lat=fields.get("lat"),
        lng=fields.get("lng"),
        description=fields.get("description"),
        estimated_cost=fields.get("estimated_cost"),
        estimated_duration_minutes=fields.get("estimated_duration_minutes"),
        # SQLAlchemy default 仅在 flush 时生效；占位 0 保证集合内可比，
        # 实际编号由 _renumber 在 flush 前统一修正
        order_index=0,
    )


def _renumber(day: TripDay) -> None:
    """按当前集合顺序重新编号 order_index（1-based，不重新排序）。"""
    for i, stop in enumerate(day.stops, start=1):
        stop.order_index = i


# ── 内部：预算重算 ──────────────────────────────────────────
def _enforce_driving_constraints(trip: Trip) -> None:
    """自驾约束门：修订后的行程若产生超距/超时的站点组合，整体拒绝。

    与规划编排的 DrivingGate 使用同一套确定性校验（driving_service），
    保证「AI 修订加了一个远距站点」这类动作不会静默落库。

    Raises:
        AppError: 存在 critical 自驾问题（400 + detail 列出具体问题）。
    """
    from app.services.driving_service import check_plan_driving

    plan_snapshot = _plan_snapshot(trip)
    driving = check_plan_driving(plan_snapshot)
    if driving["passed"]:
        return
    messages = [i.get("message", "") for i in driving["issues"] if i.get("severity") == "critical"]
    raise AppError(
        "修订后的行程存在自驾路线问题（超距/超时），已拒绝本次修改",
        code="revise_driving_violation",
        detail={"issues": messages[:5], "driving": driving},
    )


async def _recompute_budget(db: AsyncSession, trip: Trip) -> None:
    """修订后由代码重算 TripPlan.plan_data.budget（有快照则同步更新）。"""
    from app.agent.tools import compute_budget
    from app.services.driving_service import check_plan_driving

    all_stops = [
        {"name": s.name, "type": s.stop_type, "estimated_cost": float(s.estimated_cost or 0)}
        for d in trip.days
        for s in d.stops
    ]
    budget = compute_budget(all_stops)

    # 自驾报告随修订一并写回 plan 快照（前端可在修订响应 plan.driving 里看到里程/时长）
    new_days = _plan_snapshot(trip)["days"]
    driving = check_plan_driving({"days": new_days})

    # 更新最新 TripPlan 快照（若无则跳过；前端详情页主数据来自 trip 本身）
    stmt = select(TripPlan).where(TripPlan.trip_id == trip.id).order_by(TripPlan.created_at.desc())
    plan = (await db.execute(stmt)).scalars().first()
    if plan is not None:
        plan.plan_data = {
            **plan.plan_data,
            "budget": budget,
            "days": new_days,
            "driving": driving,
        }