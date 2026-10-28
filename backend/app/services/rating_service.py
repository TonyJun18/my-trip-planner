"""行程评分 / 信任信号服务（task-trip-rating-signal）。

设计（零凭证、确定性优先、诚实口径）：
- 任何登录用户可对「公开可见行程」评分（1-5）+「我去过」标记；
  可见性语义与 TripFavorite 完全一致（存在即可见，评分不扩权、不泄露新数据）。
- 同 user + trip 唯一（唯一约束）：重复提交 = 改分/翻转 visited（幂等 upsert）。
- 聚合只读：count / avg / visited_count；无评分 → avg=None（0 会被误读为差评）。
- 信任口径：avg 只来自真实用户评分，系统绝不编造/加权（与 price/rating 诚实标注一致）。
- 限流：每行程单用户提交频率由前端交互自限；服务端只做 schema 校验与幂等，
  不做额外配额（与收藏一致；如需防刷由用户后续立项 IP 限流）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Trip, TripRating, User


async def _visible_trip_or_404(db: AsyncSession, trip_id: str) -> Trip:
    """行程可见性（与收藏同语义：存在即可见，不校验 owner）。"""
    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise NotFoundError("行程不存在", code="trip_not_found")
    return trip


async def _find_rating(db: AsyncSession, trip_id: str, user_id: str) -> TripRating | None:
    stmt = select(TripRating).where(
        TripRating.trip_id == trip_id,
        TripRating.user_id == user_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_rating(
    db: AsyncSession,
    trip_id: str,
    user: User,
    *,
    rating: int,
    visited: bool,
) -> TripRating:
    """提交/更新评分（幂等 upsert；同 user+trip 唯一）。"""
    await _visible_trip_or_404(db, trip_id)
    rec = await _find_rating(db, trip_id, user.id)
    if rec is None:
        rec = TripRating(trip_id=trip_id, user_id=user.id, rating=rating, visited=visited)
        db.add(rec)
    else:
        rec.rating = rating
        rec.visited = visited
        rec.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(rec)
    return rec


async def get_rating(db: AsyncSession, trip_id: str, user: User | None) -> dict[str, Any]:
    """单行程评分详情：聚合 + 当前用户自己的评分（未登录或无评分为 None）。"""
    await _visible_trip_or_404(db, trip_id)
    agg = await rating_summary(db, [trip_id])
    mine: TripRating | None = None
    if user is not None:
        mine = await _find_rating(db, trip_id, user.id)
    summary = agg[0] if agg else {"trip_id": trip_id, "count": 0, "avg": None, "visited_count": 0}
    return {
        **summary,
        "user_rating": mine.rating if mine else None,
        "user_visited": mine.visited if mine else False,
    }


async def delete_rating(db: AsyncSession, trip_id: str, user: User) -> None:
    """删除自己的评分（幂等：无评分则 no-op）。"""
    rec = await _find_rating(db, trip_id, user.id)
    if rec is not None:
        await db.delete(rec)
        await db.commit()


async def rating_summary(
    db: AsyncSession,
    trip_ids: list[str],
) -> list[dict[str, Any]]:
    """批量聚合（画廊/列表热度）：count / avg / visited_count。"""
    ids = [t for t in trip_ids if t]
    if not ids:
        return []
    stmt = (
        select(
            TripRating.trip_id,
            func.count(TripRating.id).label("count"),
            func.avg(TripRating.rating).label("avg"),
            func.sum(case((TripRating.visited.is_(True), 1), else_=0)).label("visited_count"),
        )
        .where(TripRating.trip_id.in_(ids))
        .group_by(TripRating.trip_id)
    )
    rows = (await db.execute(stmt)).all()
    by_id = {
        row.trip_id: {
            "trip_id": row.trip_id,
            "count": int(row._mapping["count"] or 0),
            "avg": round(float(row._mapping["avg"]), 1) if row._mapping["avg"] is not None else None,
            "visited_count": int(row._mapping["visited_count"] or 0),
        }
        for row in rows
    }
    # 无评分的行程也返回 count=0（avg=None），保证与入参一一对应
    return [by_id.get(t, {"trip_id": t, "count": 0, "avg": None, "visited_count": 0}) for t in ids]