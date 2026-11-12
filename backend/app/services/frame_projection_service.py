"""相框数据投影服务（frame-marketplace）。

只读投影：把打卡数据投喂给前端相框渲染器。设计哲学与 journey_service 同源：
- **诚实口径**：只含 checked 站点；无打卡数据的日期/行程返回 empty=true，绝不推断；
- **不编造动态事实**：天气等未持久化数据一律不出现在投影里（历史日期天气 API 不可查）；
- **owner 限定**：投影包含坐标与私人备注，只对 owner 开放（非 owner 403）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Stop, Trip, TripDay


async def day_projection(db: AsyncSession, trip: Trip, day_id: str) -> dict[str, Any] | None:
    """单日打卡卡投影；day 不属于该行程返回 None（由路由层转 404）。"""
    row = await db.execute(
        select(TripDay).where(TripDay.id == day_id, TripDay.trip_id == trip.id)
    )
    day = row.scalar_one_or_none()
    if day is None:
        return None

    stops = [s for s in (day.stops or []) if s.checked]
    return {
        "trip_id": trip.id,
        "destination": trip.destination,
        "day_id": day.id,
        "day_number": day.day_number,
        "date": day.date.isoformat() if day.date else None,
        "day_note": day.note,
        "empty": not stops,
        "stops": [_stop_out(s) for s in stops],
    }


async def summary_projection(db: AsyncSession, trip: Trip) -> dict[str, Any]:
    """整程总结图投影：聚合各日 checked 站点，空日跳过。"""
    row = await db.execute(
        select(TripDay)
        .where(TripDay.trip_id == trip.id)
        .order_by(TripDay.day_number)
    )
    days = list(row.scalars().all())

    days_out: list[dict[str, Any]] = []
    checked_total = 0
    for day in days:
        stops = [s for s in (day.stops or []) if s.checked]
        if not stops:
            continue  # 空日跳过（诚实口径：不生成无内容区块）
        days_out.append({
            "day_id": day.id,
            "day_number": day.day_number,
            "date": day.date.isoformat() if day.date else None,
            "day_note": day.note,
            "stops": [_stop_out(s) for s in stops],
        })
        checked_total += len(stops)

    return {
        "trip_id": trip.id,
        "destination": trip.destination,
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "empty": not days_out,
        "stats": {
            "days_with_checkins": len(days_out),
            "total_days": len(days),
            "checked_stops": checked_total,
        },
        "days": days_out,
    }


def _stop_out(stop: Stop) -> dict[str, Any]:
    return {
        "stop_id": stop.id,
        "name": stop.name,
        "stop_type": stop.stop_type,
        "lat": stop.lat,
        "lng": stop.lng,
        "description": stop.description,
        "order_index": stop.order_index,
    }
