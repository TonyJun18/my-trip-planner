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

from app.agent.agents import CRITIC_PASS_SCORE, plan_revise_agent
from app.core.exceptions import AppError
from app.models import Stop, Trip, TripDay, TripPlan
from app.schemas import critic_fix_to_revise_diff
from app.services._common import TRIP_LOADS as _TRIP_LOADS
from app.services._common import normalize_trace as _normalize_trace


async def revise_trip(
    db: AsyncSession,
    trip_id: str,
    message: str,
    *,
    owner: str | None = None,
    provider: str = "auto",
    max_review_rounds: int = 2,
) -> dict[str, Any]:
    """执行一次行程修订，返回 {plan, summary, trace, provider, model, quality}。

    修订质控闭环（task-revise-qa-loop）：
    1. AI 生成 diff（无工具；失败可自纠正）→ 代码原子应用 + 自驾约束
    2. 主修订先落库（独立小事务）：用户请求的修订一定生效，绝不因质检回滚
    3. 修订复核 Critic（ReviseCriticAgent）审查修订后的行程：
       - 通过 → 结束
       - 未通过但给了精确 fix → 转成可执行 diff 原子应用（fix 独立小事务），再回看
       - 未通过且无 fix（大改/纯警告）→ 停在此轮（有界，不无限循环）
       - Critic 熔断/超时 → 降级为通过（质检绝不阻断合法修订）
    4. 停滞检测：修正后行程无变化（上一轮已应用过完全相同的动作）→ 强制跳出
    5. 无论是否通过，都在返回值带 quality 报告（score/passed/issues/summary），
       调用方（API ReviseOut）可透出给前端展示质检透明度。

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
    await _enforce_driving_constraints(trip)

    # 3) 主修订落库（独立小事务）——用户请求的修订一定生效。
    #    后续质检 fix 各自独立提交，任何 fix 失败都只回滚 fix，不回滚主修订。
    await db.flush()
    await _recompute_budget(db, trip)
    await db.commit()

    # 4) 修订质控闭环：Critic 复审（最多 max_review_rounds 轮；fix 独立小事务）
    quality = await _revise_qa_loop(
        db,
        trip_id,
        request={
            "destination": trip.destination,
            "travelers": trip.travelers or 1,
            "budget": trip.budget,
            "preferences": [],
            "message": message,
            "revise_summary": diff.get("summary") or "",
        },
        owner=owner,
        provider=provider,
        max_rounds=max_review_rounds,
    )

    # 5) 组装响应（终态快照：重新加载，保证 ORM 属性新鲜）
    final_trip = await _load_trip(db, trip_id, owner=owner)
    new_plan = _plan_snapshot(final_trip)
    return {
        "trip_id": trip.id,
        "summary": diff.get("summary") or "行程已更新",
        "plan": new_plan,
        "diff": _describe_actions(diff),
        "trace": _normalize_trace(revise.get("trace") or []),
        "provider": revise.get("provider"),
        "model": revise.get("model"),
        "quality": quality,
    }


# ── 内部：修订质检闭环 ────────────────────────────────────────
async def _revise_qa_loop(
    db: AsyncSession,
    trip_id: str,
    *,
    request: dict[str, Any],
    owner: str | None,
    provider: str,
    max_rounds: int,
) -> dict[str, Any] | None:
    """ReviseCritic 复审闭环（Evaluator-Optimizer，有界）。

    每轮从 DB 重新加载行程（主修订已提交，作为本轮基线），fix 应用后
    自驾约束通过才 commit（fix 独立小事务）；自驾失败 → rollback 丢弃
    本轮 fix，行程留在主修订状态，停止闭环。

    返回给前端展示的 quality 报告：pass（含 fix_applied）/ fail（无 fix）/
    degraded（Critic 失败降级）。注意：**降级视为通过**，绝不阻断合法修订。
    """
    from app.agent.agents import revise_critic_agent

    if max_rounds <= 0:
        return None  # 未开启修订复核（调用方显式关闭）

    applied_fix_count = 0
    last_fix_actions: list[tuple[Any, ...]] = []
    quality: dict[str, Any] = {
        "score": CRITIC_PASS_SCORE,
        "passed": True,
        "issues": [],
        "summary": "修订复核通过",
    }

    for _ in range(max_rounds):
        trip = await _load_trip(db, trip_id, owner=owner)
        snapshot = _plan_snapshot(trip)
        result = await revise_critic_agent(
            dict(request),
            snapshot,
            provider=provider,
        )
        critique: dict[str, Any] = result.get("critique") or {}

        if result.get("status") == "degraded":
            # Critic 熔断/超时 → 降级通过（质检是可选优化，绝不阻断修订）
            quality = {
                "score": CRITIC_PASS_SCORE,
                "passed": True,
                "issues": [],
                "summary": critique.get("summary") or "修订复核降级：质检调用失败，按通过处理",
                "degraded": True,
                "fix_applied": applied_fix_count > 0,
            }
            break

        # 通过 → 结束闭环
        if critique.get("passed"):
            quality = {
                "score": critique.get("score", CRITIC_PASS_SCORE),
                "passed": True,
                "issues": critique.get("issues") or [],
                "summary": critique.get("summary") or "修订复核通过",
                "rounds": applied_fix_count + 1,
                "fix_applied": applied_fix_count > 0,
            }
            break

        # 未通过：尝试精确 fix（CriticFixSchema → ReviseDiff，原子应用）
        fix = critique.get("fix")
        if not fix or not (fix.get("actions") or []):
            # 大改/纯警告（无精确 fix）→ 停在此轮；有界，不再重复复审
            quality = {
                "score": critique.get("score", 0),
                "passed": False,
                "issues": critique.get("issues") or [],
                "summary": critique.get("summary") or "修订复核未通过（无精确修正建议）",
                "rounds": applied_fix_count + 1,
                "fix_applied": applied_fix_count > 0,
            }
            break

        fix_diff = critic_fix_to_revise_diff(fix)
        fix_actions = fix_diff.get("actions") or []
        signature = tuple(
            (a.get("op"), a.get("day_number"), str(a.get("target") or {}), str(a.get("fields") or {}))
            for a in fix_actions
        )
        # 停滞检测：本轮 fix 与上一轮完全相同 → 再应用也无效，强制跳出
        if signature and signature in last_fix_actions:
            quality = {
                "score": critique.get("score", 0),
                "passed": False,
                "issues": critique.get("issues") or [],
                "summary": "修订复核未通过（修正建议未产生变化，已停止重试）",
                "rounds": applied_fix_count + 1,
                "fix_applied": applied_fix_count > 0,
            }
            break
        last_fix_actions.append(signature)

        # fix 应用（原子预检失败 → 停在此轮）
        try:
            _apply_diff(trip, fix_diff)
        except AppError:
            quality = {
                "score": critique.get("score", 0),
                "passed": False,
                "issues": critique.get("issues") or [],
                "summary": "修订复核未通过（精确修正无法应用）",
                "rounds": applied_fix_count + 1,
                "fix_applied": applied_fix_count > 0,
            }
            break

        # 自驾约束门：修正后若产生超距/超时 → 回滚本轮 fix 并停止（不引入新问题）
        try:
            await _enforce_driving_constraints(trip)
        except AppError as exc:
            await db.rollback()  # 丢弃未提交的 fix（trip 回到主修订状态）
            quality = {
                "score": critique.get("score", 0),
                "passed": False,
                "issues": critique.get("issues") or [],
                "summary": f"修订复核未通过：精确修正被自驾约束拒绝（{getattr(exc, 'detail', exc)}）",
                "rounds": applied_fix_count + 1,
                "fix_applied": False,
            }
            break

        # fix 落库（独立小事务）
        applied_fix_count += 1
        await db.flush()
        await _recompute_budget(db, trip)
        await db.commit()

        # 修正应用成功 → 下一轮复审（重新加载修正后的行程）
        continue

    return quality


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
    Stop 模型字段 estimated_duration_minutes；未知字段保持不变（由白名单把关）。

    也支持 Critic fix 的 plan JSON 名（type → stop_type），使修订复审
    闭环的修正 diff 与主修订 diff 走同一套字段校验。
    """
    out = dict(fields)
    if "duration_minutes" in out and "estimated_duration_minutes" not in out:
        out["estimated_duration_minutes"] = out.pop("duration_minutes")
    if "type" in out and "stop_type" not in out:
        out["stop_type"] = out.pop("type")
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
async def _enforce_driving_constraints(trip: Trip) -> None:
    """自驾约束门：修订后的行程若产生超距/超时的站点组合，整体拒绝。

    与规划编排的 DrivingGate 使用同一套确定性校验（driving_service），
    保证「AI 修订加了一个远距站点」这类动作不会静默落库。

    Raises:
        AppError: 存在 critical 自驾问题（400 + detail 列出具体问题）。
    """
    from app.services.driving_service import check_plan_driving_async

    plan_snapshot = _plan_snapshot(trip)
    driving = await check_plan_driving_async(plan_snapshot)
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
    from app.services.driving_service import check_plan_driving_async

    new_days = _plan_snapshot(trip)["days"]
    driving = await check_plan_driving_async({"days": new_days})

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