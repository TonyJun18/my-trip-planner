"""旅程全程追踪（task-journey-timeline：行中事件流投影 + 高光）。

设计哲学（与 live_service / expense_service 同源）：
- **零新表**：不落投影表，每次 GET 现算（读时聚合）——TripEvent 是唯一事实源；
- **诚实口径**：只按已产生的事件聚合；缺部分数据时 ``data_complete=False``，
  前端显示"部分数据"标识，绝不推断没发生的打卡；
- **确定性**：全部为纯函数/确定性计算，不经过 LLM；
- **事件语义对齐**：check（打卡）/ skip（跳过）/ delay（顺延）/ vote（投票）/
  comment（评论）从 TripEvent 读取，与 live_service / collab_service 一致。

投影结构（JourneyOut）：
- journey_progress: 已打卡站点数 / 总站点数 × 100（只算非酒店站点；
  行中打卡只针对 attraction/food，酒店/交通占位不计入）
- day_status[]: 按天分组（completed/partial/todo/skipped + 高光）
- expense_total / by_category / per_person: 复用 expense.compute_balance
- booking_status[]: suggested/pending/confirmed/cancelled 计数（接 TripBooking）
- highlights[]: 从事件流里挑「有故事」的（check/delay/vote/comment）
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Stop, Trip, TripBooking, TripDay, TripEvent
from app.services.live_service import trip_phase


# ── 打卡进度（纯函数） ──────────────────────────────────────────
def _non_hotel_stops(trip: Trip) -> list[Stop]:
    """行中打卡只针对 attraction/food；酒店/交通占位不计入。"""
    return [s for d in trip.days or [] for s in d.stops or [] if s.stop_type != "hotel"]


def journey_progress(trip: Trip) -> tuple[int, int, float]:
    """返回 (completed, total, progress%)。total 为 0 时 progress=0。"""
    stops = _non_hotel_stops(trip)
    total = len(stops)
    if total == 0:
        return 0, 0, 0.0
    completed = sum(1 for s in stops if s.checked)
    return completed, total, round(completed / total * 100, 1)


# ── 事件投影（读 TripEvent） ────────────────────────────────────
def _day_map(trip: Trip) -> dict[int, TripDay]:
    return {d.day_number: d for d in trip.days or []}


def _stop_name_map(trip: Trip) -> dict[str, str]:
    """stop_id → stop name（事件 payload 里只有 stop_id/name，need 展示）。"""
    return {s.id: s.name for d in trip.days or [] for s in d.stops or []}


def _day_status(day: TripDay, stops: list[Stop]) -> str:
    """一天的状态：completed（全部打卡）/ partial / todo / skipped（全被跳过）。"""
    if not stops:
        return "todo"
    non_hotel = [s for s in stops if s.stop_type != "hotel"]
    if not non_hotel:
        return "todo"
    completed = sum(1 for s in non_hotel if s.checked)
    if completed == len(non_hotel):
        return "completed"
    if completed > 0:
        return "partial"
    # 没有任何打卡：若该日所有站点被 skip 事件跳过 → skipped；否则 todo
    # （skip 是物理删除站点，无法从这里反推；用事件流补充，见 _skipped_days）
    return "todo"


def _skipped_days(events: list[TripEvent]) -> set[int]:
    """从 skip 事件反推出"整日被跳过"的天号（仅用于状态标注，不改变打卡数）。"""
    skipped: set[int] = set()
    for ev in events:
        if ev.event_type == "skip":
            day_number = (ev.payload or {}).get("day_number")
            if isinstance(day_number, int):
                skipped.add(day_number)
    return skipped


def _highlight(ev: TripEvent, stop_names: dict[str, str]) -> dict[str, Any] | None:
    """把一条事件转成高光（只挑有故事的：check/delay/vote/comment；booking 由 booking 表处理）。"""
    payload = ev.payload or {}
    day_number = payload.get("day_number")
    if ev.event_type == "check":
        name = payload.get("name") or stop_names.get(str(payload.get("stop_id")), "")
        return {
            "event_type": "check",
            "summary": f"打卡：{name}" if name else "打卡",
            "day_number": day_number,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
    if ev.event_type == "delay":
        return {
            "event_type": "delay",
            "summary": "迟到，整体顺延一天",
            "day_number": day_number,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
    if ev.event_type in ("vote", "comment") and (payload.get("summary") or payload.get("content")):
        return {
            "event_type": ev.event_type,
            "summary": payload.get("summary") or payload.get("content", ""),
            "day_number": day_number,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
    return None


async def _load_events(db: AsyncSession, trip_id: str, *, limit: int = 200) -> list[TripEvent]:
    stmt = (
        select(TripEvent)
        .where(TripEvent.trip_id == trip_id)
        .order_by(TripEvent.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


# ── 主入口 ──────────────────────────────────────────────────────
async def journey_projection(
    db: AsyncSession,
    trip: Trip,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """旅程全程追踪投影（读时聚合，零新表）。

    依赖 trip.days 已加载（relationship 已由 trip_service._TRIP_LOADS 懒加载，
    或调用方已 flush）；events / expenses / bookings 从 db 读取。

    返回值结构与 JourneyOut schema 一致。
    """
    today = today or datetime.now(timezone.utc).date()
    phase = trip_phase(trip, today=today)

    # 1) 打卡进度 + 按天状态
    completed, total, progress = journey_progress(trip)
    day_map = _day_map(trip)
    stop_name_map = _stop_name_map(trip)
    events = await _load_events(db, trip.id)
    skipped = _skipped_days(events)

    days_out: list[dict[str, Any]] = []
    for day in trip.days or []:
        stops = day.stops or []
        non_hotel = [s for s in stops if s.stop_type != "hotel"]
        day_completed = sum(1 for s in non_hotel if s.checked)
        status = "skipped" if day.day_number in skipped and day_completed == 0 else _day_status(day, stops)
        # 该日高光
        day_highlights = [
            h["summary"]
            for h in (_highlight(ev, stop_name_map) for ev in events)
            if h and h.get("day_number") == day.day_number
        ]
        days_out.append({
            "day_number": day.day_number,
            "date": day.date.isoformat() if day.date else None,
            "theme": day.note,
            "status": status,
            "completed": day_completed,
            "total": len(non_hotel),
            "highlights": day_highlights[:5],
        })

    # 2) 费用投影（复用 expense.compute_balance）
    from app.services.expense_service import _load_expenses, compute_balance

    records = await _load_expenses(db, trip.id)
    balance = compute_balance(records, travelers=trip.travelers or 1)
    by_category: dict[str, float] = {}
    for r in records:
        cat = r.category or "other"
        by_category[cat] = round(by_category.get(cat, 0.0) + (r.amount or 0.0), 2)

    # 3) 预订状态投影（接 TripBooking）
    booking_stmt = select(TripBooking).where(TripBooking.trip_id == trip.id)
    bookings = list((await db.execute(booking_stmt)).scalars().all())
    booking_status: dict[str, int] = {"suggested": 0, "pending": 0, "confirmed": 0, "cancelled": 0}
    for b in bookings:
        booking_status[b.status] = booking_status.get(b.status, 0) + 1

    # 4) 高光（全行程，最多 10 条，倒序即最新在前）
    highlights = [
        h for h in (_highlight(ev, stop_name_map) for ev in events) if h
    ][:10]

    # 5) 数据完整性（诚实口径）：每个已打卡站点（checked=True）都应有对应 check 事件。
    #    若已打卡数 > check 事件数 → 部分打卡缺事件（数据不完整）；用户根本没打卡
    #    （completed=0, check=0）是正常状态，不算不完整。
    check_event_count = sum(1 for ev in events if ev.event_type == "check")
    data_complete = completed <= check_event_count

    return {
        "trip_id": trip.id,
        "phase": phase,
        "journey_progress": progress,
        "completed_stops": completed,
        "total_stops": total,
        "days": days_out,
        "expense_total": balance.get("total", 0.0),
        "by_category": by_category,
        "per_person": balance.get("per_person", 0.0),
        "booking_status": booking_status,
        "highlights": highlights,
        "data_complete": data_complete,
    }