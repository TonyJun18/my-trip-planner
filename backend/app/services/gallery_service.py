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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Stop, Trip, TripDay
from app.services._common import TRIP_LOADS as _TRIP_LOADS
from app.services.inspiration_service import DESTINATIONS

# 模板默认天数（建议天数缺失时的兜底；诚实标注 rule_based）
DEFAULT_TEMPLATE_DAYS = 3
# 画廊单页上限
MAX_GALLERY_LIMIT = 50


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
    }


async def list_gallery(db: AsyncSession, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    """公开画廊列表（已发布 + 有分享令牌，按更新时间倒序）。"""
    limit = max(1, min(int(limit or 20), MAX_GALLERY_LIMIT))
    stmt = (
        select(Trip)
        .options(*_TRIP_LOADS)
        .where(Trip.is_featured.is_(True), Trip.share_token.is_not(None))
        .order_by(Trip.updated_at.desc())
        .limit(limit)
        .offset(max(0, int(offset or 0)))
    )
    trips = (await db.execute(stmt)).scalars().all()
    return [_gallery_summary(t) for t in trips]


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