"""旅程护照服务（task-journey-passport：行中激励 + 徽章体系）。

设计哲学（与 live_service / journey_service 同源）：
- **确定性规则**：徽章由 ``BADGE_RULES`` 纯函数判定，不经过 LLM；可测试、可解释；
- **幂等**：badges 只增不减（已拥有则跳过），重复事件不重复发徽章；
- **零新凭证**：徽章只依据已产生的事件/数据（打卡/费用/预订/修订），不采集额外信息；
- **诚实口径**：无事件不推断；未打卡不硬造"完成"；
- **与 TripEvent 联动**：``record_event`` 后 hook ``maybe_award``（独立短事务，
  失败绝不影响主流程）；历史行程用 ``backfill`` 一次性投影。

徽章规则库（7 个初始）：
- first_checkin：第一次打卡
- full_day：某天全部站点完成
- money_saver：实际花费 < 预算 90%
- train_goer / hotel_stayer：预订方案 confirmed 后触发（接 TripBooking）
- early_bird：行程开始前进过 3+ 次修订
- night_owl：有 22:00 后的 check 事件
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trip, TripBooking, TripEvent, TripPassport
from app.services.live_service import trip_phase


# ── 徽章定义 ───────────────────────────────────────────────────
BADGE_LABELS: dict[str, str] = {
    "first_checkin": "第一次打卡",
    "full_day": "完满一天",
    "money_saver": "省钱达人",
    "train_goer": "高铁行者",
    "hotel_stayer": "酒店住客",
    "early_bird": "规划狂魔",
    "night_owl": "夜猫子",
}


def _badge(key: str, earned_at: datetime | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": BADGE_LABELS.get(key, key),
        "earned_at": (earned_at or datetime.now(timezone.utc)).isoformat(),
    }


def _has_badge(passport: TripPassport, key: str) -> bool:
    return any((b or {}).get("key") == key for b in (passport.badges or []))


async def _load_events(db: AsyncSession, trip_id: str) -> list[TripEvent]:
    stmt = (
        select(TripEvent)
        .where(TripEvent.trip_id == trip_id)
        .order_by(TripEvent.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _load_bookings(db: AsyncSession, trip_id: str) -> list[TripBooking]:
    stmt = select(TripBooking).where(TripBooking.trip_id == trip_id)
    return list((await db.execute(stmt)).scalars().all())


def _check_events(events: list[TripEvent]) -> list[TripEvent]:
    return [e for e in events if e.event_type == "check"]


def _skip_days(events: list[TripEvent]) -> set[int]:
    result: set[int] = set()
    for e in events:
        if e.event_type != "skip":
            continue
        day_number = (e.payload or {}).get("day_number")
        if isinstance(day_number, int):
            result.add(day_number)
    return result


# ── 规则判定（纯函数，输入 trip + events/bookings） ────────────
def _rule_first_checkin(events: list[TripEvent]) -> bool:
    return len(_check_events(events)) >= 1


def _rule_full_day(trip: Trip, events: list[TripEvent]) -> bool:
    """某天全部非酒店站点都已打卡（跳过日不计入）。"""
    skipped = _skip_days(events)
    for day in trip.days or []:
        day_number = day.day_number
        if day_number in skipped:
            continue
        stops = [s for s in day.stops or [] if s.stop_type != "hotel"]
        if not stops:
            continue
        if all(s.checked for s in stops):
            return True
    return False


def _rule_money_saver(trip: Trip, events: list[TripEvent]) -> bool:
    """实际花费 < 预算 90%（无预算或未记账则 False）。"""
    budget = trip.budget
    if not budget:
        return False
    # 实际花费用费用表（不含某次事件——从 expense 表取，由调用方传入）
    return False  # 由 _award_for_expenses 实际判定（需要 expense 数据）


async def _rule_money_saver_async(db: AsyncSession, trip: Trip) -> bool:
    budget = trip.budget
    if not budget:
        return False
    from app.services.expense_service import _load_expenses

    records = await _load_expenses(db, trip.id)
    total = round(sum((r.amount or 0.0) for r in records), 2)
    return 0 < total < budget * 0.9


def _rule_train_goer(bookings: list[TripBooking]) -> bool:
    return any(b.kind == "train" and b.status == "confirmed" for b in bookings)


def _rule_hotel_stayer(bookings: list[TripBooking]) -> bool:
    return any(b.kind == "hotel" and b.status == "confirmed" for b in bookings)


def _rule_early_bird(trip: Trip, events: list[TripEvent]) -> bool:
    """行程开始前进过 3+ 次修订。"""
    today = datetime.now(timezone.utc).date()
    if trip.start_date > today:
        revise_count = sum(1 for e in events if e.event_type == "revise")
        return revise_count >= 3
    return False


def _rule_night_owl(events: list[TripEvent]) -> bool:
    """有 22:00 后的 check 事件。"""
    for e in _check_events(events):
        ts = e.created_at
        if ts and ts.time() >= time(22, 0):
            return True
    return False


# ── 判定 + 落库 ────────────────────────────────────────────────
async def _determine_badges(
    db: AsyncSession,
    trip: Trip,
    events: list[TripEvent],
    bookings: list[TripBooking],
) -> list[str]:
    keys: list[str] = []
    if _rule_first_checkin(events):
        keys.append("first_checkin")
    if _rule_full_day(trip, events):
        keys.append("full_day")
    if await _rule_money_saver_async(db, trip):
        keys.append("money_saver")
    if _rule_train_goer(bookings):
        keys.append("train_goer")
    if _rule_hotel_stayer(bookings):
        keys.append("hotel_stayer")
    if _rule_early_bird(trip, events):
        keys.append("early_bird")
    if _rule_night_owl(events):
        keys.append("night_owl")
    return keys


async def ensure_passport(
    db: AsyncSession,
    trip: Trip,
    *,
    commit: bool = False,
) -> TripPassport | None:
    """确保行程有护照记录（无则创建）；返回该行程护照（可能为 None=失败静默）。"""
    try:
        stmt = select(TripPassport).where(TripPassport.trip_id == trip.id)
        passport = (await db.execute(stmt)).scalars().first()
        if passport is None:
            passport = TripPassport(trip_id=trip.id, phase=trip_phase(trip))
            db.add(passport)
            await db.flush()
        else:
            passport.phase = trip_phase(trip)
        if commit:
            await db.commit()
        return passport
    except Exception:  # noqa: BLE001 — 护照失败绝不影响主流程
        return None


async def maybe_award(
    db: AsyncSession,
    trip: Trip,
) -> TripPassport | None:
    """事件后判定并颁发徽章（幂等，badges 只增不减）。

    在既有调用方事务内使用：调用方传入当前 db（通常已 flush 事件），
    本函数只读判定并更新 passport；commit 与否由调用方决定（默认不 commit）。
    """
    try:
        passport = await ensure_passport(db, trip)
        if passport is None:
            return None
        events = await _load_events(db, trip.id)
        bookings = await _load_bookings(db, trip.id)
        keys = await _determine_badges(db, trip, events, bookings)
        existing = {b.get("key") for b in (passport.badges or [])}
        new_badges = [b for b in (passport.badges or [])]
        for key in keys:
            if key not in existing:
                new_badges.append(_badge(key))
        if len(new_badges) != len(passport.badges or []):
            passport.badges = new_badges
            passport.last_progress_at = datetime.now(timezone.utc)
        return passport
    except Exception:  # noqa: BLE001
        return None


async def backfill(
    db: AsyncSession,
    trip: Trip,
) -> TripPassport | None:
    """历史行程一次性投影徽章（幂等：已拥有的不重复发）。"""
    return await maybe_award(db, trip)


async def get_passport(
    db: AsyncSession,
    trip: Trip,
) -> TripPassport:
    """查询行程护照（调用方负责加载 trip 与归属校验）。

    owner 场景：API 层先 get_trip(owner=user.id) 校验归属；
    分享场景：API 层先 get_trip_by_share_token 校验令牌。
    本函数只按 trip.id 查表；不存在时返回空护照视图（不创建行）。
    """
    stmt = select(TripPassport).where(TripPassport.trip_id == trip.id)
    passport = (await db.execute(stmt)).scalars().first()
    if passport is None:
        # 空护照（未触发过事件）：返回默认视图，不创建行
        return TripPassport(trip_id=trip.id, phase=trip_phase(trip))
    return passport


async def get_passport_by_share_token(db: AsyncSession, token: str) -> TripPassport | None:
    """凭 share_token 免登录只读护照（分享页徽章墙）。"""
    stmt = select(TripPassport).where(TripPassport.share_token == token)
    return (await db.execute(stmt)).scalars().first()


def passport_out(passport: TripPassport) -> dict[str, Any]:
    """护照 → 可序列化 dict。"""
    badges = passport.badges or []
    return {
        "trip_id": passport.trip_id,
        "phase": passport.phase,
        "badges": badges,
        "badge_count": len(badges),
        "last_progress_at": passport.last_progress_at.isoformat() if passport.last_progress_at else None,
    }