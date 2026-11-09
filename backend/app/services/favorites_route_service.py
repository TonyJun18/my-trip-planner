"""收藏 → 一键成路线服务（task-favorites-to-route）。

背景（2026-11-10 竞品分析）：问旅「收藏点变路线」是中文市场六能力里我们
唯一没有的；Plotline「收集→行程」证明是国际新入场者默认流程。此前收藏是
「死收藏」——TripFavorite 只读引用他人行程，无任何成路线动作。

设计（零凭证、最小版、与 gallery clone_trip 同构）：
- **聚合端点**：把当前用户收藏行程的站点聚合为候选（按站点名去重，
  保留来源行程标题），供前端展示「我的收藏能组出什么」。
- **一键成路线**：把某条收藏行程复制为当前用户的新草稿行程（days/stops
  全量；不复制 token / 协作数据）。**收藏即许可**：只有已收藏的关系才能
  复制（未收藏 → 404，防枚举），不需要画廊的 is_featured 前置。

与 gallery_service.clone_trip 保持同构但独立实现（不动已测画廊路径）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models import Stop, Trip, TripDay, TripFavorite, User
from app.services._common import TRIP_LOADS
from app.services import share_lifecycle

# 聚合候选上限（防收藏行程过多导致响应膨胀；默认 200，API 层可调）
DEFAULT_AGGREGATE_LIMIT = 200

# 一键成路线的副本标题后缀（与画廊「（副本）」区分来源）
ROUTE_COPY_SUFFIX = "（收藏路线）"


async def aggregate_favorite_stops(
    db: AsyncSession,
    user: User,
    *,
    limit: int = DEFAULT_AGGREGATE_LIMIT,
) -> dict[str, Any]:
    """把当前用户收藏行程的站点聚合为候选（按站点名去重，附来源行程）。

    - 返回 {items, total, trips}；items 为候选列表（name/stop_type/坐标/
      费用/时长/描述/来源行程标题），total 为去重后候选总数（可能 > limit，
      分页语义与收藏列表一致），trips 为参与聚合的收藏行程数。
    - 空收藏 / 收藏行程全部被删 → items=[], total=0, trips=0（不报错）。
    - 站点名缺失（脏数据）→ 跳过该站点，不编造。
    """
    favs = await share_lifecycle.list_favorites(db, user)
    if not favs:
        return {"items": [], "total": 0, "trips": 0}

    trip_ids = [f.trip_id for f in favs]
    stmt = select(Trip).options(*TRIP_LOADS).where(Trip.id.in_(trip_ids))
    trips = list((await db.execute(stmt)).scalars().all())

    seen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for trip in trips:
        for day in sorted(trip.days or [], key=lambda d: d.day_number or 0):
            for stop in sorted(day.stops or [], key=lambda s: s.order_index or 0):
                key = (stop.name or "").strip()
                if not key:
                    continue
                if key in seen:
                    src = seen[key]["source_trips"]
                    if trip.title not in src:
                        src.append(trip.title)
                    continue
                seen[key] = {
                    "name": key,
                    "stop_type": stop.stop_type or "attraction",
                    "lat": stop.lat,
                    "lng": stop.lng,
                    "estimated_cost": stop.estimated_cost,
                    "estimated_duration_minutes": stop.estimated_duration_minutes,
                    "description": stop.description,
                    "source_trips": [trip.title],
                }
                order.append(key)

    items = [seen[k] for k in order[:limit]]
    return {"items": items, "total": len(seen), "trips": len(trips)}


async def create_route_from_favorite(
    db: AsyncSession,
    trip_id: str,
    user: User,
) -> Trip:
    """一键成路线：把收藏的行程复制为当前用户的新草稿行程。

    权限：**必须是当前用户已收藏的行程**（收藏即许可）。未收藏 /
    行程不存在 → 404（与画廊 clone 同款防枚举风格，不泄露他人行程存在性）。

    复制语义与 gallery_service.clone_trip 对齐：
    - 复制：title（加「（收藏路线）」后缀）/ destination / departure /
      trip_type / start_date / end_date / travelers / budget / days / stops
      （含坐标 / 费用 / 时长 / description / details，checked 重置）
    - **不复制**：share_token / edit_token / is_featured / 评论 / 投票 /
      评分（协作数据属原行程）。
    - 新行程 status="draft"，owner=当前用户。
    """
    fav_stmt = select(TripFavorite).where(
        TripFavorite.user_id == user.id,
        TripFavorite.trip_id == trip_id,
    )
    fav = (await db.execute(fav_stmt)).scalar_one_or_none()
    if fav is None:
        raise NotFoundError("行程不存在或未收藏", code="trip_not_found")

    src_stmt = select(Trip).options(*TRIP_LOADS).where(Trip.id == trip_id)
    src = (await db.execute(src_stmt)).scalar_one_or_none()
    if src is None:  # 收藏关系在但行程被删（级联下理论不可达，防御）
        raise NotFoundError("行程不存在", code="trip_not_found")

    copy = Trip(
        owner=user.id,
        title=f"{src.title}{ROUTE_COPY_SUFFIX}"[:200],
        destination=src.destination,
        departure=src.departure,
        trip_type=src.trip_type,
        start_date=src.start_date,
        end_date=src.end_date,
        travelers=src.travelers,
        budget=src.budget,
        status="draft",
        is_featured=False,
    )
    db.add(copy)
    await db.flush()

    for day in sorted(src.days or [], key=lambda d: d.day_number or 0):
        new_day = TripDay(trip_id=copy.id, day_number=day.day_number, date=day.date, note=day.note)
        db.add(new_day)
        await db.flush()
        for stop in sorted(day.stops or [], key=lambda s: s.order_index or 0):
            db.add(Stop(
                day_id=new_day.id,
                order_index=stop.order_index,
                name=stop.name,
                stop_type=stop.stop_type,
                lat=stop.lat,
                lng=stop.lng,
                description=stop.description,
                estimated_cost=stop.estimated_cost,
                estimated_duration_minutes=stop.estimated_duration_minutes,
                checked=False,
                details=dict(stop.details or {}) or None,
            ))
    await db.commit()

    # 重新 eager-load（TripOut 序列化需要 days/stops；避免异步上下文外懒加载）
    stmt2 = select(Trip).options(*TRIP_LOADS).where(Trip.id == copy.id)
    return (await db.execute(stmt2)).scalar_one()