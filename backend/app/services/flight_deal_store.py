"""机票特价的持久层 + 用户确认（FlightDeals 的 DB 侧）。

分层原因：
- ``flight_deals_service`` 保持纯函数/无 DB（解析、闸门、排序、内存缓存）；
- 本模块负责「读快照 / 写快照 / 用户确认落 TripBooking / 事件联动」，
  让 API 层与 agent 层共用同一套口径。

口径红线：
- 确认选择 ≠ 已订。落库状态一律 ``pending``（已选未出票），只有带凭证才能进
  ``confirmed``（沿用 booking_service 状态机）；
- ``amount`` 存「起价 × 人数」的合计参考金额，标题里明确标注「起价」，不做实价断言。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.models import FlightDealSnapshot, Trip, TripBooking
from app.services.flight_deals_service import (
    CACHE_TTL_SECONDS,
    PARTIAL_CACHE_TTL_SECONDS,
    collect_flight_deals,
    route_key,
)

logger = get_logger(__name__)

# 价格来源 → 预订渠道（provider 语义是「去哪儿订」，不是「价格从哪来」）
_SOURCE_PROVIDER: dict[str, str] = {
    "skyscanner": "trip",
    "tianxun.com": "trip",
    "skyscanner.net": "trip",
    "skyscanner.com": "trip",
    "trip.com": "trip",
    "ctrip.com": "ctrip",
    "qunar.com": "qunar",
    "fliggy.com": "feizhu",
    "ly.com": "tongcheng",
}


class FlightChoiceError(AppError):
    """机票选择非法（方案不存在/缺少必要字段）。"""

    status_code = 400
    code = "flight_choice_invalid"


def request_from_trip(trip: Trip) -> dict[str, Any]:
    """从 Trip 组装采集请求（与 PlanRequest 同字段名，便于复用 agent 层逻辑）。"""
    return {
        "departure": trip.departure or "",
        "destination": trip.destination or "",
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "travelers": trip.travelers or 1,
    }


# ── 快照读写 ───────────────────────────────────────────────────
async def read_snapshot(
    db: AsyncSession,
    key: str,
    *,
    fresh_only: bool = True,
) -> FlightDealSnapshot | None:
    """按 route_key 取最新快照（fresh_only=True 时只返回未过期的）。"""
    stmt = (
        select(FlightDealSnapshot)
        .where(FlightDealSnapshot.route_key == key)
        .order_by(FlightDealSnapshot.fetched_at.desc())
        .limit(1)
    )
    snapshot = (await db.execute(stmt)).scalars().first()
    if snapshot is None:
        return None
    if fresh_only and snapshot.expires_at <= datetime.now(timezone.utc):
        return None
    return snapshot


async def save_snapshot(
    db: AsyncSession,
    key: str,
    payload: dict[str, Any],
) -> FlightDealSnapshot:
    """写入快照（同一 route_key 只保留最新一条，避免表无限增长）。"""
    await db.execute(delete(FlightDealSnapshot).where(FlightDealSnapshot.route_key == key))
    fetched_at = datetime.now(timezone.utc)
    has_options = bool(payload.get("options"))
    ttl = CACHE_TTL_SECONDS if has_options else PARTIAL_CACHE_TTL_SECONDS
    snapshot = FlightDealSnapshot(
        route_key=key,
        provider=(payload.get("provider") or "tavily")[:32],
        payload=payload,
        status=(payload.get("status") or "degraded")[:20],
        options_count=len(payload.get("options") or []),
        hit_count=0,
        fetched_at=fetched_at,
        expires_at=fetched_at + timedelta(seconds=ttl),
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_flight_deals(
    db: AsyncSession,
    trip: Trip,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """行程机票推荐视图：优先读未过期快照，否则实时采集并落库。"""
    request = request_from_trip(trip)
    if not request["departure"]:
        payload = await collect_flight_deals(request)
        return {**payload, "is_cached": False, "travelers": request["travelers"]}

    key = route_key(request)
    if not refresh:
        snapshot = await read_snapshot(db, key)
        if snapshot is not None:
            snapshot.hit_count = (snapshot.hit_count or 0) + 1
            await db.commit()
            return {**snapshot.payload, "is_cached": True, "travelers": request["travelers"]}

    payload = await collect_flight_deals(request, refresh=refresh)
    payload["travelers"] = request["travelers"]
    if payload.get("options") or payload.get("promos"):
        try:
            await save_snapshot(db, key, payload)
        except Exception as exc:  # noqa: BLE001 — 落库失败不影响本次返回
            logger.warning("机票快照落库失败 route=%s err=%s", key, exc)
    return {**payload, "is_cached": False}


# ── 用户确认 ───────────────────────────────────────────────────
async def current_choice(db: AsyncSession, trip_id: str) -> TripBooking | None:
    """行程当前已选的机票（kind=flight 且未取消）。"""
    stmt = (
        select(TripBooking)
        .where(
            TripBooking.trip_id == trip_id,
            TripBooking.kind == "flight",
            TripBooking.status.in_(("suggested", "pending", "confirmed")),
        )
        .order_by(TripBooking.updated_at.desc(), TripBooking.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


def _resolve_option(
    payload: dict[str, Any] | None,
    option_id: str | None,
) -> dict[str, Any] | None:
    for option in (payload or {}).get("options") or []:
        if isinstance(option, dict) and option.get("option_id") == option_id:
            return option
    return None


def _provider_for(option: dict[str, Any]) -> str:
    source = str(option.get("source") or "").lower()
    url = str(option.get("source_url") or "").lower()
    for key, provider in _SOURCE_PROVIDER.items():
        if key in source or key in url:
            return provider
    return "manual"


async def choose_flight(
    db: AsyncSession,
    trip: Trip,
    *,
    option_id: str | None = None,
    manual_option: dict[str, Any] | None = None,
    travelers: int | None = None,
) -> tuple[TripBooking, dict[str, Any] | None]:
    """确认一个机票方案 → 写 TripBooking(kind=flight, status=pending)。

    - ``option_id``：从当前快照的方案里选（找不到 → 400，提示刷新）；
    - ``manual_option``：用户自己找的航班（必须带 title + price + currency）；
    - 幂等：同一行程已有 flight 预订则原地更新，不新增重复条目；
    - 事件：记 ``edit`` + ``payload.kind="flight_choice"``（协作提示白名单内）。
    """
    request = request_from_trip(trip)
    payload = await get_flight_deals(db, trip)
    option: dict[str, Any] | None = None

    if option_id:
        option = _resolve_option(payload, option_id)
        if option is None:
            raise FlightChoiceError(
                "机票方案已过期或不存在，请刷新后重选",
                detail={"trip_id": trip.id, "option_id": option_id},
            )
    elif manual_option:
        title = str(manual_option.get("title") or "").strip()
        price = manual_option.get("price")
        currency = str(manual_option.get("currency") or "").strip().upper()
        if not title or not isinstance(price, (int, float)) or price <= 0 or not currency:
            raise FlightChoiceError(
                "手动方案必须包含 title / price / currency",
                detail={"trip_id": trip.id},
            )
        option = {
            "option_id": "manual",
            "strategy": "manual",
            "title": title[:200],
            "price": float(price),
            "currency": currency,
            "price_kind": "from",
            "airlines": manual_option.get("airlines") or [],
            "outbound_date": manual_option.get("outbound_date"),
            "inbound_date": manual_option.get("inbound_date"),
            "source": manual_option.get("source") or "manual",
            "source_url": manual_option.get("source_url"),
            "confidence": float(manual_option.get("confidence") or 0.5),
            "note": manual_option.get("note") or "用户手动填写",
        }
    else:
        raise FlightChoiceError("缺少 option_id 或 option", detail={"trip_id": trip.id})

    count = travelers if travelers and travelers > 0 else (request.get("travelers") or 1)
    price = float(option.get("price") or 0)
    currency = str(option.get("currency") or "CNY")
    amount = round(price * count, 2)
    title = f"{option.get('title') or '机票'}（{count} 人合计，起价）"[:300]

    existing = await current_choice(db, trip.id)
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.provider = _provider_for(option)
        existing.title = title
        existing.provider_url = (option.get("source_url") or existing.provider_url or "")[:500] or None
        existing.amount = amount
        existing.currency = currency[:10]
        existing.status = "pending"
        existing.reference = "plan.generated"
        existing.updated_at = now
        booking = existing
    else:
        booking = TripBooking(
            trip_id=trip.id,
            kind="flight",
            provider=_provider_for(option),
            title=title,
            provider_url=(option.get("source_url") or "")[:500] or None,
            status="pending",
            reference="plan.generated",
            amount=amount,
            currency=currency[:10],
        )
        db.add(booking)
    await db.commit()
    await db.refresh(booking)

    try:
        from app.services.event_service import record_event

        await record_event(
            db,
            trip_id=trip.id,
            event_type="edit",
            payload={
                "kind": "flight_choice",
                "booking_id": booking.id,
                "option_id": option.get("option_id"),
                "title": option.get("title"),
                "price": price,
                "currency": currency,
                "travelers": count,
                "status": "pending",
            },
            commit=False,
        )
    except Exception as exc:  # noqa: BLE001 — 事件失败不影响确认结果
        logger.warning("机票选择事件记录失败 trip=%s err=%s", trip.id, exc)

    return booking, option


async def clear_choice(
    db: AsyncSession,
    trip: Trip,
    *,
    booking_id: str | None = None,
) -> None:
    """撤销机票选择（删除对应的 flight 预订条目；无则 404）。"""
    stmt = select(TripBooking).where(
        TripBooking.trip_id == trip.id,
        TripBooking.kind == "flight",
    )
    if booking_id:
        stmt = stmt.where(TripBooking.id == booking_id)
    booking = (await db.execute(stmt.order_by(TripBooking.created_at.desc()))).scalars().first()
    if booking is None:
        raise NotFoundError("机票选择不存在", code="flight_choice_not_found")
    await db.delete(booking)
    await db.commit()
