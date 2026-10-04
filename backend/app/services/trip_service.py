"""行程领域服务：行程 / 日程 / 站点的增删改查（支持 owner 隔离）。"""
from __future__ import annotations

from datetime import date
from secrets import token_urlsafe

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models import Stop, Trip, TripDay, TripPlan
from app.schemas import DayIn, StopIn, StopUpdate, TripCreate, TripUpdate
from app.services._common import TRIP_LOADS as _TRIP_LOADS

logger = get_logger(__name__)


async def _record_behavior_safely(
    db: AsyncSession,
    *,
    user_id: str | None,
    signal_kind: str,
    destination: str,
    actions: list[dict],
    summary: str,
) -> None:
    """行为记忆回写（task-travel-memory-feedback 触点，fire-and-forget）。

    主操作已在调用方 flush；这里先 commit 提交主操作（API 层后续 commit
    为 no-op），再用独立小事务写行为记忆——记忆写失败仅回滚记忆本身，
    绝不阻断（或回滚）主流程。
    """
    if not user_id:
        return
    try:
        await db.commit()  # 提交主操作（已 flush）
        from app.services import profile_service

        await profile_service._record_behavior(
            db,
            user_id=user_id,
            signal_kind=signal_kind,
            destination=destination,
            actions=actions,
            summary=summary,
        )
        await db.commit()  # 独立小事务：只提交行为记忆
    except Exception:  # noqa: BLE001 — 行为记忆是可丢弃的，绝不阻断主流程
        logger.debug("行为记忆回写失败（已忽略）", exc_info=True)
        await db.rollback()


def _owner_expr(owner: str | None):
    """owner 过滤表达式：None（匿名）匹配 owner IS NULL，保证匿名也隔离。"""
    if owner is None:
        return Trip.owner.is_(None)
    return Trip.owner == owner


async def _load_trip(db: AsyncSession, trip_id: str, *, owner: str | None = None) -> Trip:
    stmt = select(Trip).options(*_TRIP_LOADS).where(Trip.id == trip_id).where(_owner_expr(owner))
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("行程不存在", code="trip_not_found")
    return trip


async def list_trips(
    db: AsyncSession, *, offset: int = 0, limit: int = 50, owner: str | None = None
) -> tuple[list[Trip], int]:
    stmt_count = select(func.count()).select_from(Trip).where(_owner_expr(owner))
    total = (await db.execute(stmt_count)).scalar_one()
    stmt = (
        select(Trip)
        .options(*_TRIP_LOADS)
        .where(_owner_expr(owner))
        .order_by(Trip.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    trips = list((await db.execute(stmt)).scalars().all())
    return trips, total


async def get_trip(db: AsyncSession, trip_id: str, *, owner: str | None = None) -> Trip:
    return await _load_trip(db, trip_id, owner=owner)


async def get_plan(db: AsyncSession, trip_id: str, *, owner: str | None = None) -> TripPlan | None:
    """查询行程的 AI 规划方案快照（owner 隔离）。"""
    await _load_trip(db, trip_id, owner=owner)  # 校验行程存在 + 归属
    return await get_plan_by_trip_id(db, trip_id)


async def get_plan_by_trip_id(db: AsyncSession, trip_id: str) -> TripPlan | None:
    """按 trip_id 直接查 AI 规划方案快照（不做 owner 校验）。

    用于已通过「分享/编辑令牌」校验访问权的场景（trip 本身已确认可见），
    避免再用 owner=None 过滤导致持有真实 owner 的分享行程查不到。
    """
    stmt = select(TripPlan).where(TripPlan.trip_id == trip_id).order_by(TripPlan.created_at.desc())
    return (await db.execute(stmt)).scalars().first()


async def ensure_plan_transport(
    db: AsyncSession, trip: Trip, plan: TripPlan | None,
) -> dict:
    """读路径惰性补全：老行程 plan.transport 为空时，轻量生成参考方案并写回。

    背景：transport/discount_rules 回填只在「新规划」时发生；此功能上线前落库的
    行程 plan_data.transport 恒为 null/空，详情页/分享页看不到大交通、预算也不算。
    本函数在读取 plan 时检测缺省并触发一次轻量补全（高德驾车 + 规则参考价，
    不调用当前网络不可达的慢速 Tavily），成功后写回 plan_data（请求结束时由
    session 依赖提交）；失败静默返回原数据，绝不阻断读取。

    返回补全后的 plan_data。
    """
    if plan is None:
        return {}
    data = plan.plan_data or {}
    transport = data.get("transport")
    if isinstance(transport, dict) and transport.get("options"):
        return data  # 已有方案，无需补全
    departure = (trip.departure or "").strip()
    destination = (trip.destination or "").strip()
    if not departure or not destination:
        return data  # 缺出发地/目的地 → 无法生成，保持原样
    try:
        from app.agent import tools as agent_tools
        from app.services.budget_service import transport_round_trip_cost

        fallback = await agent_tools.fetch_transport_fallback(
            departure, destination, timeout=8,
        )
        if not fallback.get("options"):
            return data
        data["transport"] = fallback
        # 同步预算口径：往返参考价并入 by_type.transport 与总额（与 compute_budget 同口径）
        tcost = transport_round_trip_cost(data)
        if tcost is not None:
            budget = data.setdefault("budget", {})
            by_type = budget.setdefault("by_type", {})
            by_type["transport"] = tcost
            budget["total_estimated"] = round(
                float(budget.get("total_estimated") or 0.0) + tcost, 2
            )
        plan.plan_data = data
        logger.info("读路径交通补全 trip=%s options=%d", trip.id, fallback.get("count", 0))
    except Exception as exc:  # noqa: BLE001 — 补全失败绝不阻断读取
        logger.debug("读路径交通补全失败 trip=%s err=%s", trip.id, exc)
    return data


# ── 分享（只读链接） ────────────────────────────────────────
async def create_share_token(db: AsyncSession, trip_id: str, *, owner: str | None = None) -> str:
    """为行程生成（或复用）只读分享令牌。需要行程归属校验。"""
    trip = await _load_trip(db, trip_id, owner=owner)
    if not trip.share_token:
        trip.share_token = token_urlsafe(32)
        await db.flush()
    return trip.share_token


async def get_trip_by_share_token(db: AsyncSession, token: str) -> Trip:
    """按分享令牌读取行程（免登录只读，持令牌即视为授权——与 git secret link 同语义）。

    - 不存在的令牌 → 404（避免泄露行程是否存在）
    - 生命周期门禁：share_tokens 表有记录且已过期/吊销 → 410/403
      （旧令牌无记录 → 永久兼容，不受影响）
    - 任何人都可查询，不做 owner 校验（分享的语义就是跨用户只读）
    """
    stmt = select(Trip).options(*_TRIP_LOADS).where(Trip.share_token == token)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("分享链接无效或已失效", code="share_token_invalid")
    from app.services import share_lifecycle

    rec = await share_lifecycle.ensure_share_token_record(db, trip, kind="share")
    share_lifecycle.raise_if_token_inactive(rec)
    await share_lifecycle.touch_token_usage(db, rec)
    return trip


# ── 受邀编辑（edit_token：编辑权与只读分享分离，owner 可随时收回） ────
async def create_edit_token(db: AsyncSession, trip_id: str, *, owner: str | None = None) -> str:
    """为行程生成（或复用）受邀编辑令牌。需要行程归属校验。

    - 与 share_token 独立：不开放编辑时旧分享链接保持只读，安全边界清晰。
    - 幂等：已生成则复用（share_token 同语义）。
    """
    trip = await _load_trip(db, trip_id, owner=owner)
    if not trip.edit_token:
        trip.edit_token = token_urlsafe(32)
        await db.flush()
    return trip.edit_token


async def revoke_edit_token(db: AsyncSession, trip_id: str, *, owner: str | None = None) -> None:
    """收回受邀编辑权：清空 edit_token（不影响只读分享链接）。"""
    trip = await _load_trip(db, trip_id, owner=owner)
    if trip.edit_token:
        trip.edit_token = None
        await db.flush()


async def get_trip_by_edit_token(db: AsyncSession, token: str) -> Trip:
    """按受邀编辑令牌读取行程（编辑权包含只读，受邀者可查看完整行程）。

    与只读 share_token 的信任语义一致：持令牌即视为授权，令牌不存在 → 404。
    同样受生命周期门禁（share_tokens.kind='edit' 过期/吊销 → 410/403）。
    """
    stmt = select(Trip).options(*_TRIP_LOADS).where(Trip.edit_token == token)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("协作编辑链接无效或已失效", code="edit_token_invalid")
    from app.services import share_lifecycle

    rec = await share_lifecycle.ensure_share_token_record(db, trip, kind="edit")
    share_lifecycle.raise_if_token_inactive(rec)
    await share_lifecycle.touch_token_usage(db, rec)
    return trip


async def create_trip(db: AsyncSession, data: TripCreate, *, owner: str | None = None) -> Trip:
    trip = Trip(**data.model_dump(), owner=owner)
    db.add(trip)
    await db.flush()
    return await _load_trip(db, trip.id, owner=owner)


async def update_trip(db: AsyncSession, trip_id: str, data: TripUpdate, *, owner: str | None = None) -> Trip:
    trip = await _load_trip(db, trip_id, owner=owner)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(trip, field, value)
    await db.flush()
    return await _load_trip(db, trip_id, owner=owner)


async def delete_trip(db: AsyncSession, trip_id: str, *, owner: str | None = None) -> None:
    trip = await _load_trip(db, trip_id, owner=owner)
    await db.delete(trip)
    await db.flush()


async def delete_day(db: AsyncSession, day_id: str, *, owner: str | None = None) -> None:
    """删除一个日程（级联删除其下站点）。先校验所属行程归属，防越权删除。"""
    day = await _load_day_for_owner(db, day_id, owner=owner)
    await db.delete(day)
    await db.flush()


async def delete_stop(db: AsyncSession, stop_id: str, *, owner: str | None = None) -> None:
    """删除一个站点。先校验所属行程归属，防越权删除。"""
    stop = await db.get(Stop, stop_id)
    if stop is None:
        raise NotFoundError("站点不存在", code="stop_not_found")
    day = await _load_day_for_owner(db, stop.day_id, owner=owner)
    name = stop.name
    await db.delete(stop)
    await db.flush()
    # 行为记忆触点：手动删除站点（显式加载 Trip，避免 lazy load MissingGreenlet）
    trip = await db.get(Trip, day.trip_id)
    await _record_behavior_safely(
        db,
        user_id=owner,
        signal_kind="manual_remove",
        destination=trip.destination if trip else "",
        actions=[{"op": "remove", "target": {"name": name}}],
        summary=f"删除站点：{name}",
    )


async def add_day(db: AsyncSession, trip_id: str, data: DayIn, *, owner: str | None = None) -> TripDay:
    trip = await _load_trip(db, trip_id, owner=owner)
    if any(d.day_number == data.day_number for d in trip.days):
        from app.core.exceptions import ConflictError

        raise ConflictError(f"第 {data.day_number} 天已存在")
    day = TripDay(trip_id=trip.id, **data.model_dump())
    db.add(day)
    await db.flush()
    # eager-load stops，避免序列化 DayOut.stops 时 MissingGreenlet
    stmt = select(TripDay).options(selectinload(TripDay.stops)).where(TripDay.id == day.id)
    return (await db.execute(stmt)).scalar_one()


async def add_stop(db: AsyncSession, day_id: str, data: StopIn, *, owner: str | None = None) -> Stop:
    stmt = select(TripDay).options(selectinload(TripDay.stops)).where(TripDay.id == day_id)
    day = (await db.execute(stmt)).scalar_one_or_none()
    if day is None:
        raise NotFoundError("日程不存在", code="day_not_found")
    max_order = (
        await db.execute(select(func.max(Stop.order_index)).where(Stop.day_id == day_id))
    ).scalar()
    stop = Stop(day_id=day_id, order_index=(max_order or 0) + 1, **data.model_dump())
    db.add(stop)
    await db.flush()
    await db.refresh(stop)
    # 行为记忆触点：手动新增站点（显式加载 Trip，避免 lazy load 在 async 下 MissingGreenlet）
    trip = await db.get(Trip, day.trip_id)
    await _record_behavior_safely(
        db,
        user_id=owner,
        signal_kind="manual_add",
        destination=trip.destination if trip else "",
        actions=[{"op": "add", "fields": {"name": stop.name, "type": stop.stop_type}}],
        summary=f"新增站点：{stop.name}",
    )
    return stop


async def _load_day_for_owner(db: AsyncSession, day_id: str, *, owner: str | None = None) -> TripDay:
    """加载日程并校验其所属行程归属当前用户（站点级写操作统一走这里）。"""
    day = await db.get(TripDay, day_id)
    if day is None:
        raise NotFoundError("日程不存在", code="day_not_found")
    # 触发所属行程的 owner 校验；不匹配时 _load_trip 抛 NotFound
    await _load_trip(db, day.trip_id, owner=owner)
    return day


async def update_stop(
    db: AsyncSession, day_id: str, stop_id: str, data: StopUpdate, *, owner: str | None = None
) -> Stop:
    """手动编辑站点字段：仅更新显式传入的字段（exclude_unset），其余保持原值。"""
    day = await _load_day_for_owner(db, day_id, owner=owner)
    stop = await db.get(Stop, stop_id)
    if stop is None or stop.day_id != day.id:
        raise NotFoundError("站点不存在", code="stop_not_found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(stop, field, value)
    await db.flush()
    await db.refresh(stop)
    # 行为记忆触点：手动编辑站点（显式加载 Trip，避免 lazy load MissingGreenlet）
    trip = await db.get(Trip, day.trip_id)
    changed = data.model_dump(exclude_unset=True)
    await _record_behavior_safely(
        db,
        user_id=owner,
        signal_kind="manual_edit",
        destination=trip.destination if trip else "",
        actions=[{"op": "replace", "target": {"name": stop.name}, "fields": changed}],
        summary=f"编辑站点：{stop.name}" + (f"（{', '.join(changed.keys())}）" if changed else ""),
    )
    return stop


async def reorder_stops(
    db: AsyncSession, day_id: str, order: list[str], *, owner: str | None = None
) -> list[Stop]:
    """整日站点重排：order 必须包含该日全部站点 id（乱序/缺漏 → 400），按序重写 order_index。"""
    day = await _load_day_for_owner(db, day_id, owner=owner)
    stmt = select(Stop).where(Stop.day_id == day.id).order_by(Stop.order_index)
    stops = list((await db.execute(stmt)).scalars().all())
    if len(order) != len(stops) or set(order) != {s.id for s in stops}:
        from app.core.exceptions import AppError

        raise AppError("顺序列表必须包含该日全部站点", code="stop_order_invalid")
    by_id = {s.id: s for s in stops}
    for idx, stop_id in enumerate(order, start=1):
        by_id[stop_id].order_index = idx
    await db.flush()
    for s in stops:
        await db.refresh(s)
    # 按请求的新顺序返回（而非按旧 order_index 排序）
    return [by_id[sid] for sid in order]


async def generate_days_for_range(
    db: AsyncSession, trip_id: str, start: date, end: date, *, note: str | None = None, owner: str | None = None
) -> list[TripDay]:
    """按日期范围批量生成 Day（含边界检查）。

    上限 31 天（与 PlanSchema 一致）：防止一次请求插入数年（1825+ 天）的
    非法数据量；超限抛 ConflictError。
    """
    trip = await _load_trip(db, trip_id, owner=owner)
    if end < start:
        from app.core.exceptions import ConflictError

        raise ConflictError("结束日期不能早于开始日期")
    if (end - start).days + 1 > 31:
        from app.core.exceptions import ConflictError

        raise ConflictError("日期范围不能超过 31 天")
    existing = {d.day_number for d in trip.days}
    created: list[TripDay] = []
    for i, d in enumerate(_daterange(start, end), start=1):
        if i in existing:
            continue
        day = TripDay(trip_id=trip.id, day_number=i, date=d, note=note)
        db.add(day)
        created.append(day)
    await db.flush()
    return created


def _daterange(start: date, end: date):
    from datetime import timedelta

    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)