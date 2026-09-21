"""行程领域服务：行程 / 日程 / 站点的增删改查（支持 owner 隔离）。"""
from __future__ import annotations

from datetime import date
from secrets import token_urlsafe

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models import Stop, Trip, TripDay, TripPlan
from app.schemas import DayIn, StopIn, TripCreate, TripUpdate

# 统一 eager-load 关系，避免序列化时 async lazy load 报 MissingGreenlet
_TRIP_LOADS = (selectinload(Trip.days).selectinload(TripDay.stops),)


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
    stmt = select(TripPlan).where(TripPlan.trip_id == trip_id).order_by(TripPlan.created_at.desc())
    return (await db.execute(stmt)).scalars().first()


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
    - 任何人都可查询，不做 owner 校验（分享的语义就是跨用户只读）
    """
    stmt = select(Trip).options(*_TRIP_LOADS).where(Trip.share_token == token)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("分享链接无效或已失效", code="share_token_invalid")
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
    """删除一个日程（级联删除其下站点）。"""
    day = await db.get(TripDay, day_id)
    if day is None:
        raise NotFoundError("日程不存在", code="day_not_found")
    await db.delete(day)
    await db.flush()


async def delete_stop(db: AsyncSession, stop_id: str, *, owner: str | None = None) -> None:
    """删除一个站点。"""
    stop = await db.get(Stop, stop_id)
    if stop is None:
        raise NotFoundError("站点不存在", code="stop_not_found")
    await db.delete(stop)
    await db.flush()


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
    return stop


async def generate_days_for_range(
    db: AsyncSession, trip_id: str, start: date, end: date, *, note: str | None = None, owner: str | None = None
) -> list[TripDay]:
    """按日期范围批量生成 Day（含边界检查）。"""
    trip = await _load_trip(db, trip_id, owner=owner)
    if end < start:
        from app.core.exceptions import ConflictError

        raise ConflictError("结束日期不能早于开始日期")
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