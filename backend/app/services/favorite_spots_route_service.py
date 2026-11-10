"""收藏地点 → 一键成路线 服务（task-social-favorites-flow-eval 第二段聚合）。

背景（2026-11-10 竞品分析）：Plotline collect-first 闭环 = 攒地点（隐藏
向已做）→ **成路线（本模块）**。收藏行程 → 复制成草稿（favorites_route_service）
是另一条链路；本模块是从「收藏地点（FavoriteSpot）」**从零生成**一条新行程，
两者语义不同、互不依赖。

设计（零凭证、纯规则、确定性；见 openspec/changes/favorite-spots-to-route）：
- ``assign_spots_to_days``：纯函数，把勾选地点分到 N 天。酒店每天至多 1 家且
  置于该日首位；非酒店地点在「全部有坐标」时按 (lat, lng) 字典序排序（可复现），
  否则保持勾选顺序；顺序装箱，每天 ≤ MAX_STOPS_PER_DAY（复用 time_validation
  权威常量，不硬编码）。溢出（放不下的 others / 多于天数的 hotels）诚实计数。
- ``create_route_from_spots``：按 id 查**本人**收藏（不存在/他人 → skipped 计入
  报告，不 404 整单）；全无效 → 400。单事务批量建 Trip + N 个 TripDay + 全部
  Stop（lat/lng 原样保留、checked=False、order_index 从 1 起）；不触发行为记忆
  （模板生成，与 create_route_from_favorite 同构）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models import FavoriteSpot, Stop, Trip, TripDay, User
from app.schemas.favorite_spots import FavoriteRouteIn
from app.services._common import TRIP_LOADS
from app.services.time_validation import MAX_STOPS_PER_DAY


# ── 纯函数：确定性分天 ────────────────────────────────────────


def assign_spots_to_days(
    spots: list[dict[str, Any]],
    days: int,
    start_date: date,
) -> dict[str, Any]:
    """把勾选地点确定性分到 N 天（每天 ≤ MAX_STOPS_PER_DAY）。

    spots: 富 dict 列表（来自 FavoriteSpot ORM，顺序 = 用户勾选顺序），
           每项含 name / stop_type / lat / lng / description /
           estimated_cost / estimated_duration_minutes。

    规则（同输入同输出，可单测）：
    1. hotels = stop_type == 'hotel'：第 i 家放桶 i（i < days）首位，其余溢出；
    2. others：全部有坐标 → 按 (lat, lng) 字典序；否则保持勾选顺序；
    3. others 依序放入「容量未满的最小编号桶」（hotel 已占位则剩 4 位）；
    4. 溢出 = 未放下的 others 数 + hotel_overflow；placed = 实际入桶数。

    返回 {"days": [{day_number, date, stops: [spot...]}], "placed",
          "overflow", "hotel_overflow"}。stops 内 spot 保留输入 dict 原字段。
    """
    if days < 1:
        raise ValueError("days 必须 >= 1")
    if not spots:
        return {"days": [], "placed": 0, "overflow": 0, "hotel_overflow": 0, "skipped": 0}

    hotels = [s for s in spots if (s.get("stop_type") or "attraction") == "hotel"]
    others = [s for s in spots if (s.get("stop_type") or "attraction") != "hotel"]

    # others 排序：全部有坐标 → 字典序；否则保持勾选顺序（缺坐标不丢弃不报错）
    all_have_coords = all(
        s.get("lat") is not None and s.get("lng") is not None for s in others
    )
    if all_have_coords:
        others = sorted(others, key=lambda s: (s["lat"], s["lng"]))

    # 桶初始化：{day_number: 1..days, stops: [], hotel_placed: bool}
    buckets: list[dict[str, Any]] = [
        {"day_number": i + 1, "date": start_date + timedelta(days=i), "stops": [], "has_hotel": False}
        for i in range(days)
    ]

    # 1. 酒店锚定：第 i 家 → 桶 i 首位
    hotel_overflow = 0
    for i, hotel in enumerate(hotels):
        if i < days:
            b = buckets[i]
            b["stops"].append(hotel)
            b["has_hotel"] = True
        else:
            hotel_overflow += 1

    # 2. others 顺序装箱：容量未满的最小编号桶
    placed_others = 0
    overflow = 0
    for spot in others:
        target = next(
            (b for b in buckets if len(b["stops"]) < MAX_STOPS_PER_DAY),
            None,
        )
        if target is None:
            overflow += 1
            continue
        target["stops"].append(spot)
        placed_others += 1

    placed = len(hotels[:days]) + placed_others
    return {
        "days": [
            {"day_number": b["day_number"], "date": b["date"], "stops": b["stops"]}
            for b in buckets
            if b["stops"]
        ],
        "placed": placed,
        "overflow": overflow,
        "hotel_overflow": hotel_overflow,
    }


# ── 服务层：从收藏地点生成行程 ──────────────────────────────


def _spot_to_dict(spot: FavoriteSpot) -> dict[str, Any]:
    """FavoriteSpot ORM → 富 dict（保持字段名与 Stop 构造兼容）。"""
    return {
        "id": spot.id,
        "name": spot.name,
        "stop_type": spot.stop_type,
        "lat": spot.lat,
        "lng": spot.lng,
        "description": spot.description,
        "estimated_cost": spot.estimated_cost,
        "estimated_duration_minutes": spot.estimated_duration_minutes,
    }


async def create_route_from_spots(
    db: AsyncSession,
    user: User,
    data: FavoriteRouteIn,
) -> dict[str, Any]:
    """从收集箱地点生成一条新草稿行程。

    - 只读本人收藏：spot_ids 里不存在/属于他人的 id → skipped（不 404 整单，
      防枚举）；一个有效 id 都不剩 → AppError 400。
    - 单事务批量创建 Trip + N 个 TripDay + 全部 Stop；lat/lng 原样保留
      （缺坐标不编造），checked=False，order_index 从 1 起。
    - 返回 {"trip": Trip (TRIP_LOADS eager-load), "report": {placed, overflow,
      hotel_overflow, skipped}}。
    """
    found = []
    if data.spot_ids:
        stmt = select(FavoriteSpot).where(
            FavoriteSpot.user_id == user.id,
            FavoriteSpot.id.in_(data.spot_ids),
        )
        rows = list((await db.execute(stmt)).scalars().all())
        by_id = {s.id: s for s in rows}
        # 保持勾选顺序（spot_ids 顺序即勾选顺序）；缺失的 id 计入 skipped
        found = [by_id[sid] for sid in data.spot_ids if sid in by_id]

    skipped = len(data.spot_ids) - len(found)
    if not found:
        raise AppError("没有有效的收藏地点", code="no_valid_spots")

    spots = [_spot_to_dict(s) for s in found]
    assignment = assign_spots_to_days(spots, data.days, data.start_date)

    end_date = data.start_date + timedelta(days=data.days - 1)
    trip = Trip(
        owner=user.id,
        title=data.title.strip()[:200],
        destination=data.destination.strip()[:200],
        start_date=data.start_date,
        end_date=end_date,
        travelers=data.travelers,
        status="draft",
        is_featured=False,
    )
    db.add(trip)
    await db.flush()

    for day in assignment["days"]:
        new_day = TripDay(trip_id=trip.id, day_number=day["day_number"], date=day["date"])
        db.add(new_day)
        await db.flush()
        for idx, spot in enumerate(day["stops"], start=1):
            db.add(
                Stop(
                    day_id=new_day.id,
                    order_index=idx,
                    name=spot["name"],
                    stop_type=spot["stop_type"],
                    lat=spot["lat"],
                    lng=spot["lng"],
                    description=spot["description"],
                    estimated_cost=spot["estimated_cost"],
                    estimated_duration_minutes=spot["estimated_duration_minutes"],
                    checked=False,
                )
            )
    await db.commit()

    # 重新 eager-load（TripOut 序列化需要 days/stops；created_at 由 DB 填充）
    stmt2 = select(Trip).options(*TRIP_LOADS).where(Trip.id == trip.id)
    trip_loaded = (await db.execute(stmt2)).scalar_one()

    report = {
        "placed": assignment["placed"],
        "overflow": assignment["overflow"],
        "hotel_overflow": assignment["hotel_overflow"],
        "skipped": skipped,
    }
    return {"trip": trip_loaded, "report": report}