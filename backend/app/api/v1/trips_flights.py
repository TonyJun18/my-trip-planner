"""机票特价 API（FlightDeals：全网收集 → 2–3 个方案 → 用户确认）。

端点（挂 /trips 前缀）：
- GET    /trips/{trip_id}/flight-deals    —— 机票推荐（owner；refresh=1 强制重采）
- POST   /trips/{trip_id}/flight-choice   —— 确认一个方案（写 TripBooking kind=flight）
- DELETE /trips/{trip_id}/flight-choice   —— 撤销选择

信任语义与 booking/expense 一致：owner 可写；分享链接持有人只读（本接口不开放给分享令牌，
后续如需要可在 trips_share 的分享视图里只读暴露，不暴露凭证类字段）。

口径：``price_kind=from``，确认选择 ≠ 已订（status=pending，未出票）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.flight import (
    FlightChoiceIn,
    FlightChoiceOut,
    FlightDealsOut,
)
from app.services import flight_deal_store
from app.services.trip_service import get_trip

router = APIRouter()


@router.get(
    "/{trip_id}/flight-deals",
    response_model=FlightDealsOut,
    summary="行程机票特价推荐（owner）",
)
async def get_trip_flight_deals(
    trip_id: str,
    refresh: int = Query(default=0, ge=0, le=1, description="1=忽略缓存强制重新采集"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FlightDealsOut:
    """返回 2–3 个机票方案 + 促销摘要 + 当前已选方案。

    - 优先读未过期快照（6h TTL）；``refresh=1`` 强制重采（前端手动刷新用）；
    - 无出发地 / 采集失败 → ``status=skipped|degraded`` 且 options 为空，
      前端展示降级文案，绝不返回编造价格；
    - 每条 option 必须带 source_url 与 price_kind=from（硬闸门保证）。
    """
    trip = await get_trip(db, trip_id, owner=user.id)
    payload = await flight_deal_store.get_flight_deals(db, trip, refresh=bool(refresh))
    selected = await flight_deal_store.current_choice(db, trip_id)
    return FlightDealsOut(
        trip_id=trip_id,
        route=payload.get("route") or {},
        fetched_at=payload.get("fetched_at"),
        provider=payload.get("provider"),
        status=payload.get("status") or "degraded",
        price_kind=payload.get("price_kind") or "from",
        options=payload.get("options") or [],
        promos=payload.get("promos") or [],
        note=payload.get("note"),
        is_cached=bool(payload.get("is_cached")),
        selected=_booking_to_selected(selected),
        selected_booking_id=selected.id if selected else None,
    )


@router.post(
    "/{trip_id}/flight-choice",
    response_model=FlightChoiceOut,
    summary="确认一个机票方案（owner）",
)
async def choose_trip_flight(
    trip_id: str,
    data: FlightChoiceIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FlightChoiceOut:
    """把用户选中的方案写成 TripBooking（kind=flight, status=pending）。

    - 语义：**已选未出票**；只有补凭证后走 booking 状态机才能进 confirmed；
    - 幂等：同一行程再次选择会原地更新同一条条目；
    - 事件：记 edit + payload.kind=flight_choice（协作者会收到变更提示）。
    """
    trip = await get_trip(db, trip_id, owner=user.id)
    booking, option = await flight_deal_store.choose_flight(
        db, trip,
        option_id=data.option_id,
        manual_option=data.option,
        travelers=data.travelers,
    )
    return FlightChoiceOut(
        trip_id=trip_id,
        booking_id=booking.id,
        status=booking.status,
        reference=booking.reference,
        amount=booking.amount,
        currency=booking.currency,
        title=booking.title,
        provider_url=booking.provider_url,
        option=option,
        updated_at=booking.updated_at,
    )


@router.delete(
    "/{trip_id}/flight-choice",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="撤销机票选择（owner）",
)
async def clear_trip_flight_choice(
    trip_id: str,
    booking_id: str | None = Query(default=None, description="指定要撤销的预订 id；缺省撤销最新一条"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """撤销机票选择（删除对应 flight 预订条目；不影响行程其他内容）。"""
    trip = await get_trip(db, trip_id, owner=user.id)
    await flight_deal_store.clear_choice(db, trip, booking_id=booking_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _booking_to_selected(booking: Any) -> dict | None:
    """把已选预订投影成前端卡片需要的字段（不含凭证类敏感字段）。"""
    if booking is None:
        return None
    return {
        "booking_id": booking.id,
        "title": booking.title,
        "amount": booking.amount,
        "currency": booking.currency,
        "status": booking.status,
        "provider": booking.provider,
        "provider_url": booking.provider_url,
        "updated_at": booking.updated_at.isoformat() if booking.updated_at else None,
    }
