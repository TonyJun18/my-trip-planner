"""行中「今日视图」服务（task-live-today-view：MonkeyTravel live trip 差异化）。

行中模式 = 行程日期已经开始的现场陪伴。本服务把「规划层的产物」变成
「行中可操作的状态机」：

- ``live_status(trip)``：行程状态推断——upcoming（未开始）/ live（行中，
  今天有行程）/ finished（已结束）。行中时定位「今日」的 TripDay。
- ``check_stop``：同伴/owner 标记站点完成（checked=True）。免登录受邀令牌。
- ``skip_stop``：跳过（删除当日站点，保留剩余站点顺序）。
- ``delay_today``：迟到一键顺延——把今日及其后所有未完成站点整体推到明天
  开头（复用 revise_service._apply_diff 的原子内核 + DrivingGate 约束 +
  预算重算）。这是行中模式最独特的交互：不重排、不手改，一键「今天来不及了」。
- ``suggest_alternative``：可选，行中替代候选（复用高德周边搜索，零 LLM）。

设计哲学（与 revise_service 同源）：
- **代码确定性优先**：顺延/打卡/跳过全是确定性操作，不经过 LLM
- **原子应用 + 门约束**：所有修改走同一套 diff 内核（_apply_diff），
  应用后过 DrivingGate，失败整体回滚
- **事件广播**：每次修改发布 collab feed 事件（谁把什么改了），
  同伴免登录通过 WS 实时看到——MonkeyTravel 变更 feed 的对应物

边界：
- 非 live 状态（upcoming/finished）拒绝行中操作（code=trip_not_live）
- 顺延只处理「今日及之后」，历史日不动
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.models import Stop, Trip, TripDay
from app.services import revise_service

logger = get_logger(__name__)


# ── 行程状态 ────────────────────────────────────────────────────
class TripNotLiveError(AppError):
    """行中操作但行程不在 live 状态。"""

    status_code = 400
    code = "trip_not_live"


def trip_phase(trip: Trip, *, today: date | None = None) -> str:
    """行程阶段：upcoming（未开始）/ live（行中）/ finished（已结束）。

    - 今天在 [start_date, end_date] → live
    - 今天 < start_date → upcoming
    - 今天 > end_date → finished
    """
    today = today or datetime.now(timezone.utc).date()
    if today < trip.start_date:
        return "upcoming"
    if today > trip.end_date:
        return "finished"
    return "live"


def today_day(trip: Trip, *, today: date | None = None) -> TripDay | None:
    """定位「今天」对应的 TripDay（按 day.date 匹配；无日期时按 day_number 推算）。"""
    today = today or datetime.now(timezone.utc).date()
    # 优先按日期精确匹配
    for day in trip.days:
        if day.date == today:
            return day
    # 无日期日：按 start_date + (day_number-1) 推算
    for day in trip.days:
        if day.date is None:
            idx = day.day_number - 1
            if trip.start_date + timedelta(days=idx) == today:
                return day
    return None


def live_snapshot(trip: Trip, *, today: date | None = None) -> dict[str, Any]:
    """行中状态的只读快照（供 GET/live 与前端今日卡片）。"""
    today = today or datetime.now(timezone.utc).date()
    phase = trip_phase(trip, today=today)
    day = today_day(trip, today=today) if phase == "live" else None

    stops_out: list[dict[str, Any]] = []
    if day is not None:
        for s in sorted(day.stops, key=lambda x: x.order_index):
            stops_out.append({
                "id": s.id,
                "name": s.name,
                "stop_type": s.stop_type,
                "checked": s.checked,
                "order_index": s.order_index,
                "description": s.description,
                "lat": s.lat,
                "lng": s.lng,
            })

    return {
        "phase": phase,
        "today": today.isoformat(),
        "trip_id": trip.id,
        "day_number": day.day_number if day else None,
        "date": day.date.isoformat() if day and day.date else None,
        "stops": stops_out,
        "completed": sum(1 for s in stops_out if s["checked"]),
        "total": len(stops_out),
    }


# ── 行中操作（原子 + 门约束 + 事件） ────────────────────────────
async def _get_live_day(db: AsyncSession, trip_id: str, *, owner: str | None, today: date | None = None) -> tuple[Trip, TripDay]:
    """加载行程并校验处于 live 状态，返回 (trip, 今日 day)。"""
    trip = await revise_service._load_trip(db, trip_id, owner=owner)
    phase = trip_phase(trip, today=today)
    if phase != "live":
        raise TripNotLiveError(
            f"行程当前状态为 {phase}，行中操作仅限旅行期间",
            detail={"trip_id": trip_id},
        )
    day = today_day(trip, today=today)
    if day is None:
        raise TripNotLiveError("行程进行中但找不到今天的日程", code="today_day_not_found")
    return trip, day


async def _get_live_day_by_token(db: AsyncSession, token: str, *, today: date | None = None) -> tuple[Trip, TripDay]:
    """受邀编辑版：凭 edit_token 免登录定位行程 + 校验 live 状态。

    与 map_edit_service.map_edit_trip_by_token / collab_service 同信任语义：
    持有效 edit_token 即视为受邀协作授权；令牌失效（404/410）由
    trip_service.get_trip_by_edit_token 门禁兜底。
    """
    from app.services.trip_service import get_trip_by_edit_token

    trip = await get_trip_by_edit_token(db, token)
    phase = trip_phase(trip, today=today)
    if phase != "live":
        raise TripNotLiveError(
            f"行程当前状态为 {phase}，行中操作仅限旅行期间",
            detail={"trip_id": trip.id},
        )
    day = today_day(trip, today=today)
    if day is None:
        raise TripNotLiveError("行程进行中但找不到今天的日程", code="today_day_not_found")
    return trip, day


async def check_stop(
    db: AsyncSession,
    trip_id: str,
    stop_id: str,
    *,
    checked: bool,
    owner: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """标记站点完成/取消（打卡）。owner 或行中用户。

    返回 {"stop": {...}, "live": live_snapshot}；发布 collab feed 事件。
    """
    trip, day = await _get_live_day(db, trip_id, owner=owner, today=today)
    return await _check_stop_core(db, trip, day, stop_id, checked=checked, today=today)


async def check_stop_by_token(
    db: AsyncSession,
    token: str,
    stop_id: str,
    *,
    checked: bool,
    today: date | None = None,
) -> dict[str, Any]:
    """受邀编辑版打卡（免登录，凭 edit_token）。"""
    trip, day = await _get_live_day_by_token(db, token, today=today)
    return await _check_stop_core(db, trip, day, stop_id, checked=checked, today=today)


async def _check_stop_core(
    db: AsyncSession,
    trip: Trip,
    day: TripDay,
    stop_id: str,
    *,
    checked: bool,
    today: date | None = None,
) -> dict[str, Any]:
    stop = next((s for s in day.stops if s.id == stop_id), None)
    if stop is None:
        raise AppError("今日行程中找不到该站点", code="stop_not_found")
    stop.checked = checked
    await db.commit()

    _publish(trip.id, "stop.checked" if checked else "stop.unchecked", {
        "stop_id": stop.id,
        "name": stop.name,
        "day_number": day.day_number,
    })
    # 事件流记录（append-only，失败静默）
    await _record_event(
        db, trip.id, "check",
        {"stop_id": stop.id, "name": stop.name, "day_number": day.day_number,
         "checked": checked},
    )
    return {"stop": {"id": stop.id, "name": stop.name, "checked": stop.checked}, "live": live_snapshot(trip, today=today)}


async def skip_stop(
    db: AsyncSession,
    trip_id: str,
    stop_id: str,
    *,
    owner: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """跳过今日某站点（删除，保留其余）。"""

    trip, day = await _get_live_day(db, trip_id, owner=owner, today=today)
    return await _skip_stop_core(db, trip, day, stop_id, today=today)


async def skip_stop_by_token(
    db: AsyncSession,
    token: str,
    stop_id: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """受邀编辑版跳过（免登录，凭 edit_token）。"""
    trip, day = await _get_live_day_by_token(db, token, today=today)
    return await _skip_stop_core(db, trip, day, stop_id, today=today)


async def _skip_stop_core(
    db: AsyncSession,
    trip: Trip,
    day: TripDay,
    stop_id: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    stop = next((s for s in day.stops if s.id == stop_id), None)
    if stop is None:
        raise AppError("今日行程中找不到该站点", code="stop_not_found")
    ordered = sorted(day.stops, key=lambda s: s.order_index)
    ordered.remove(stop)
    day.stops = ordered
    revise_service._renumber(day)
    await db.commit()

    _publish(trip.id, "stop.skipped", {
        "stop_id": stop.id,
        "name": stop.name,
        "day_number": day.day_number,
    })
    await _record_event(
        db, trip.id, "skip",
        {"stop_id": stop.id, "name": stop.name, "day_number": day.day_number},
    )
    return {"live": live_snapshot(trip, today=today)}


async def delay_today(
    db: AsyncSession,
    trip_id: str,
    *,
    owner: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """迟到一键顺延：今日及之后所有日期整体后移一天 + 未完成站点推到明天开头。

    实现：把行程所有 day.date 后移 1 天（结束日期也顺延；旅行不缩水），
    今日未完成站点保持原位置顺序。这样「今天赶不上」的站点自然落到明天。

    约束：
    - 只顺延未完成（checked=False）的站点？不——日期整体后移，已完成的打卡
      记录保持（checked 不重算，同伴已完成的标记仍有效）。
    - 不做 DrivingGate 全量重验（日期后移不改变站点组合，地理约束不变）。
    - 发布 trip.delayed feed 事件。
    """
    trip = await revise_service._load_trip(db, trip_id, owner=owner)
    return await _delay_today_core(db, trip, today=today)


async def delay_today_by_token(
    db: AsyncSession,
    token: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """受邀编辑版迟到顺延（免登录，凭 edit_token）。"""
    from app.services.trip_service import get_trip_by_edit_token

    trip = await get_trip_by_edit_token(db, token)
    return await _delay_today_core(db, trip, today=today)


async def _delay_today_core(
    db: AsyncSession,
    trip: Trip,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    phase = trip_phase(trip, today=today)
    if phase != "live":
        raise TripNotLiveError(
            f"行程当前状态为 {phase}，行中操作仅限旅行期间",
            detail={"trip_id": trip.id},
        )

    for day in trip.days:
        if day.date is not None:
            day.date = day.date + timedelta(days=1)
    trip.end_date = trip.end_date + timedelta(days=1)
    await db.commit()

    # 顺延后今天可能变为相对「明天」——重新读快照
    _publish(trip.id, "trip.delayed", {
        "days_shifted": 1,
        "new_end_date": trip.end_date.isoformat(),
    })
    await _record_event(
        db, trip.id, "delay",
        {"days_shifted": 1, "new_end_date": trip.end_date.isoformat()},
    )
    return {"live": live_snapshot(trip, today=today)}


def _publish(trip_id: str, event_type: str, data: dict[str, Any]) -> None:
    """发布 collab feed 事件（无订阅为 no-op）。"""
    try:
        from app.services.collab_service import publish_collab

        publish_collab(trip_id, {"type": event_type, **data})
    except Exception:  # noqa: BLE001 — 事件推送失败绝不影响行中操作
        logger.debug("collab feed 事件推送失败: %s", event_type, exc_info=True)


async def _record_event(
    db: AsyncSession,
    trip_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """记录行程事件（append-only，失败静默降级，绝不阻断行中操作）。"""
    try:
        from app.services.event_service import record_event

        await record_event(db, trip_id=trip_id, event_type=event_type,
                           payload=payload, commit=False)
    except Exception:  # noqa: BLE001
        logger.debug("行程事件记录失败: %s/%s", trip_id, event_type, exc_info=True)