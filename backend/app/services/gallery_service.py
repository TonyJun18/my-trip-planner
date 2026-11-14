"""公开灵感画廊 + 城市模板（task-gallery-featured + task-gallery-city-templates）。

背景：Trip Planner AI Community Trips / Mindtrip Inspiration / Wonderplan 模板库
三方共识——「社区内容库」是行程工具的低成本留存抓手；我们此前只有私人 favorites。

设计（零新凭证、确定性优先）：
- **画廊**：owner 主动把已分享的行程发布到精选（``is_featured=True`` + 一句话卖点），
  公开列表返回摘要（目的地/天数/预算/卖点/分享令牌），访客可「以此为基础创建」
  → ``clone_trip`` 复制一份到自己的账号（复用行程/日程/站点，不复制令牌与协作数据）。
- **城市模板**：直接由 ``inspiration_service.DESTINATIONS``（23 目的地知识库）
  生成模板卡（目的地/建议天数/预算档/标签/日均预算），零 LLM、零维护；
  前端深链到 PlanWizard 预填创建（复用现有 prefill 链路）。
- 诚实口径：模板 ``basis="rule_based"``，画廊内容为真实用户分享（``source="user"``）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import GalleryLike, Stop, Trip, TripDay, TripRating
from app.services._common import TRIP_LOADS as _TRIP_LOADS
from app.services.inspiration_service import DESTINATIONS

# 模板默认天数（建议天数缺失时的兜底；诚实标注 rule_based）
DEFAULT_TEMPLATE_DAYS = 3
# 画廊单页上限
MAX_GALLERY_LIMIT = 50
# 排序口径：new=最近更新 / hot=评分热度（评分人数 → 均分 → 更新时间）
GALLERY_SORTS = ("new", "hot")


def city_templates(limit: int = 20) -> list[dict[str, Any]]:
    """城市模板卡（来自 23 目的地知识库，规则生成，零 LLM）。

    返回字段：destination / country / days / budget_tier / est_daily_budget /
    tags / best_season / title / basis。
    """
    limit = max(1, min(int(limit or 20), MAX_GALLERY_LIMIT))
    out: list[dict[str, Any]] = []
    for dest in DESTINATIONS[:limit]:
        name = str(dest.get("name") or "").strip()
        if not name:
            continue
        days = int(dest.get("suggested_days") or DEFAULT_TEMPLATE_DAYS)
        out.append({
            "destination": name,
            "country": dest.get("country") or "",
            "days": max(1, min(days, 14)),
            "budget_tier": dest.get("budget_tier") or "comfort",
            "est_daily_budget": dest.get("est_daily_budget"),
            "tags": list(dest.get("tags") or []),
            "best_season": dest.get("best_season") or "all",
            "title": f"{name} {max(1, min(days, 14))} 日模板",
            "basis": "rule_based",
        })
    return out


def _gallery_summary(trip: Trip) -> dict[str, Any]:
    """画廊卡片摘要（不含 owner/令牌以外的敏感信息；令牌用于只读消费）。"""
    return {
        "trip_id": trip.id,
        "title": trip.title,
        "destination": trip.destination,
        "days": len(trip.days or []),
        "travelers": trip.travelers,
        "budget": trip.budget,
        "blurb": trip.gallery_blurb or "",
        "share_token": trip.share_token,
        "updated_at": trip.updated_at.isoformat() if trip.updated_at else None,
        "source": "user",
        "is_featured": True,
        # 评分热度（task-trip-rating-signal）：默认无评分；由 list_gallery 填充
        "rating_count": 0,
        "rating_avg": None,
        "visited_count": 0,
        # 画廊点赞（ADR-0001）：默认 0；由 list_gallery 填充
        "like_count": 0,
        "liked": False,
    }


async def _attach_rating_summaries(
    db: AsyncSession, summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """批量附加评分热度（count / avg / visited_count）；失败不影响列表（尽力而为）。"""
    if not summaries:
        return summaries
    from app.services import rating_service

    try:
        trip_ids = [s["trip_id"] for s in summaries]
        agg = await rating_service.rating_summary(db, trip_ids)
        agg_by_id = {a["trip_id"]: a for a in agg}
        for s in summaries:
            a = agg_by_id.get(s["trip_id"])
            if a:
                s["rating_count"] = a["count"]
                s["rating_avg"] = a["avg"]
                s["visited_count"] = a["visited_count"]
    except Exception:  # noqa: BLE001 — 聚合失败不阻断画廊读取（诚实降级为无评分）
        pass
    return summaries


async def list_gallery(
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    sort: str = "new",
    destination: str | None = None,
    owner: str | None = None,
    viewer_id: str | None = None,
) -> dict[str, Any]:
    """公开画廊列表（已发布 + 有分享令牌）。

    返回 ``{items, total, limit, offset}``——``total`` 是**过滤后的真实总数**
    （此前返回 ``len(items)``，前端无法做分页）。

    - ``sort``：``new`` 最近更新 / ``hot`` 评分热度（人数 → 均分 → 更新时间）
    - ``destination``：目的地模糊匹配（画廊筛选条）
    - ``owner``：只列某个 owner 的发布（「我发布的」；由 API 层从登录态取）
    - ``viewer_id``：当前浏览者（登录时传），用于附加「我是否赞过」（liked）
    """
    limit = max(1, min(int(limit or 20), MAX_GALLERY_LIMIT))
    offset = max(0, int(offset or 0))
    sort = sort if sort in GALLERY_SORTS else "new"

    conditions: list[Any] = [Trip.is_featured.is_(True), Trip.share_token.is_not(None)]
    dest = (destination or "").strip()
    if dest:
        conditions.append(Trip.destination.ilike(f"%{dest}%"))
    if owner:
        conditions.append(Trip.owner == owner)

    total = int(
        (await db.execute(select(func.count(Trip.id)).where(*conditions))).scalar_one() or 0
    )

    if sort == "hot":
        # 评分聚合作子查询后 join：排序在 SQL 里做，分页才不会错位
        agg = (
            select(
                TripRating.trip_id.label("trip_id"),
                func.count(TripRating.id).label("cnt"),
                func.avg(TripRating.rating).label("avg"),
            )
            .group_by(TripRating.trip_id)
            .subquery()
        )
        stmt = (
            select(Trip)
            .options(*_TRIP_LOADS)
            .outerjoin(agg, agg.c.trip_id == Trip.id)
            .where(*conditions)
            .order_by(
                func.coalesce(agg.c.cnt, 0).desc(),
                func.coalesce(agg.c.avg, 0).desc(),
                Trip.updated_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    else:
        stmt = (
            select(Trip)
            .options(*_TRIP_LOADS)
            .where(*conditions)
            .order_by(Trip.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )

    trips = (await db.execute(stmt)).scalars().all()
    summaries = await _attach_rating_summaries(db, [_gallery_summary(t) for t in trips])
    # 附加点赞数（独立于评分，不参与 hot 排序；失败不影响列表）
    like_map = await like_summaries(db, [s["trip_id"] for s in summaries])
    for s in summaries:
        s["like_count"] = like_map.get(s["trip_id"], 0)
    # 附加「我是否赞过」（viewer 登录时）：画廊卡 ❤ 状态
    if viewer_id and summaries:
        liked_rows = (
            await db.execute(
                select(GalleryLike.trip_id).where(
                    GalleryLike.trip_id.in_([s["trip_id"] for s in summaries]),
                    GalleryLike.user_id == viewer_id,
                )
            )
        ).scalars().all()
        liked_ids = set(liked_rows)
        for s in summaries:
            s["liked"] = s["trip_id"] in liked_ids
    return {"items": summaries, "total": total, "limit": limit, "offset": offset}


async def publish_to_gallery(
    db: AsyncSession, trip_id: str, *, owner: str, blurb: str | None = None,
) -> dict[str, Any]:
    """owner 发布行程到精选画廊（自动确保分享令牌存在，不泄露 edit_token）。"""
    from app.services import trip_service

    trip = await trip_service.get_trip(db, trip_id, owner=owner)
    if not trip.share_token:
        # 复用分享令牌创建（幂等：已有则沿用）
        await trip_service.create_share_token(db, trip_id, owner=owner)
        await db.refresh(trip)
    trip.is_featured = True
    trip.gallery_blurb = (blurb or "").strip()[:200] or None
    await db.commit()
    await db.refresh(trip)
    return _gallery_summary(trip)


async def unpublish_from_gallery(db: AsyncSession, trip_id: str, *, owner: str) -> None:
    """owner 从画廊撤回（只清 is_featured，不影响分享链接）。"""
    from app.services import trip_service

    trip = await trip_service.get_trip(db, trip_id, owner=owner)
    trip.is_featured = False
    await db.commit()


async def clone_trip(db: AsyncSession, source_id: str, *, new_owner: str) -> Trip:
    """「以此为基础创建」：把画廊行程复制一份到当前账号（站点/日程全量，非令牌）。

    不复制：share_token / edit_token / is_featured / 评论 / 投票（协作数据属原行程）。
    """
    stmt = select(Trip).options(*_TRIP_LOADS).where(Trip.id == source_id)
    src = (await db.execute(stmt)).scalar_one_or_none()
    if src is None:
        raise NotFoundError("行程不存在")
    if not src.is_featured and src.owner != new_owner:
        # 未发布的他人行程不可复制（除本人外）
        raise NotFoundError("行程不存在")

    copy = Trip(
        owner=new_owner,
        title=f"{src.title}（副本）"[:200],
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
    stmt2 = select(Trip).options(*_TRIP_LOADS).where(Trip.id == copy.id)
    return (await db.execute(stmt2)).scalar_one()


async def _require_featured_trip(db: AsyncSession, trip_id: str) -> Trip:
    """点赞目标必须存在且已发布到画廊（featured + share_token）。"""
    stmt = select(Trip).where(Trip.id == trip_id)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None or not trip.is_featured or not trip.share_token:
        raise NotFoundError("行程不存在或未发布到画廊")
    return trip


async def like_trip(db: AsyncSession, trip_id: str, *, user_id: str) -> dict[str, Any]:
    """登录用户点赞画廊行程（幂等 toggle）。

    - owner 不可自赞（自赞无社区意义，403）。
    - 返回 {liked: True, like_count: N}；重复点赞不再新增（同 user+trip 唯一）。
    """
    trip = await _require_featured_trip(db, trip_id)
    if trip.owner == user_id:
        raise PermissionDeniedError("不能给自己的行程点赞")

    existing = (
        await db.execute(
            select(GalleryLike).where(GalleryLike.trip_id == trip_id, GalleryLike.user_id == user_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(GalleryLike(trip_id=trip_id, user_id=user_id))
        await db.commit()

    count = int(
        (await db.execute(
            select(func.count(GalleryLike.id)).where(GalleryLike.trip_id == trip_id)
        )).scalar_one() or 0
    )
    return {"liked": True, "like_count": count}


async def unlike_trip(db: AsyncSession, trip_id: str, *, user_id: str) -> dict[str, Any]:
    """取消点赞（幂等：未赞过也返回成功，like_count 不变）。"""
    await _require_featured_trip(db, trip_id)
    existing = (
        await db.execute(
            select(GalleryLike).where(GalleryLike.trip_id == trip_id, GalleryLike.user_id == user_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await db.commit()
    count = int(
        (await db.execute(
            select(func.count(GalleryLike.id)).where(GalleryLike.trip_id == trip_id)
        )).scalar_one() or 0
    )
    return {"liked": False, "like_count": count}


async def like_summaries(db: AsyncSession, trip_ids: list[str]) -> dict[str, int]:
    """批量统计点赞数（画廊列表附加用；失败不影响主流程）。"""
    if not trip_ids:
        return {}
    try:
        rows = (
            await db.execute(
                select(GalleryLike.trip_id, func.count(GalleryLike.id))
                .where(GalleryLike.trip_id.in_(trip_ids))
                .group_by(GalleryLike.trip_id)
            )
        ).all()
        return {tid: int(cnt) for tid, cnt in rows}
    except Exception:  # noqa: BLE001 — 尽力而为，失败返回空
        return {}


async def set_featured_by_staff(db: AsyncSession, trip_id: str, *, blurb: str | None = None) -> dict[str, Any]:
    """staff 将任意公开行程标为画廊精选（ADR-0001 运营能力）。

    - 目标行程必须存在且已分享（share_token 非空）；未分享则自动创建分享令牌。
    - 不要求 owner 自助 publish：staff 可直接 feature 任意公开行程。
    - 幂等：重复调用只更新 blurb。
    """
    from app.services import trip_service

    trip = (
        await db.execute(select(Trip).options(*_TRIP_LOADS).where(Trip.id == trip_id))
    ).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("行程不存在")
    if not trip.share_token:
        # 自动确保分享令牌存在（staff 精选需要公开可消费）
        await trip_service.create_share_token(db, trip_id, owner=trip.owner)
        await db.refresh(trip)
    trip.is_featured = True
    trip.gallery_blurb = (blurb or "").strip()[:200] or trip.gallery_blurb
    await db.commit()
    await db.refresh(trip)
    return _gallery_summary(trip)