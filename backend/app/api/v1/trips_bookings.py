"""预订 API（task-booking-outlink：可预订建议 + 凭证回填 + 状态机）。

端点（挂 /trips 前缀，路径字面量在 /{trip_id} 之前注册，避免路由吞参）：
- GET    /trips/{trip_id}/bookings           —— 预订列表（owner）
- POST   /trips/{trip_id}/bookings           —— 新增/回填一条预订（owner）
- POST   /trips/{trip_id}/bookings/{booking_id}/status —— 更新状态（confirm/cancel）
- DELETE /trips/{trip_id}/bookings/{booking_id}        —— 删除（owner）

与 expense 同信任语义：owner 可写；share/edit token 只读（在 trips_share 的
分享视图里只读展示预订状态，不暴露凭证号给只读链接持有者）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import BookingIn, BookingListOut, BookingOut, BookingStatusIn
from app.services import booking_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get(
    "/{trip_id}/bookings",
    response_model=BookingListOut,
    summary="行程预订列表（owner）",
)
async def list_trip_bookings(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> BookingListOut:
    """owner 查看行程的预订条目（建议 + 回填 + 状态）。"""
    items = await booking_service.list_bookings(db, trip_id, owner=user.id)
    return BookingListOut(
        items=[BookingOut.model_validate(b) for b in items],
        total=len(items),
    )


@router.post(
    "/{trip_id}/bookings",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增/回填一条预订（owner）",
)
async def add_trip_booking(
    trip_id: str,
    data: BookingIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> BookingOut:
    """owner 新增一条预订（suggested 建议 / user.confirmed 回填凭证）。"""
    booking = await booking_service.upsert_booking(db, trip_id, data, owner=user.id)
    return BookingOut.model_validate(booking)


@router.post(
    "/{trip_id}/bookings/{booking_id}/status",
    response_model=BookingOut,
    summary="更新预订状态（confirm/cancel）",
)
async def update_trip_booking_status(
    trip_id: str,
    booking_id: str,
    data: BookingStatusIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> BookingOut:
    """owner 更新预订状态：suggested → pending → confirmed ⇄ cancelled。

    - 进入 confirmed 必须带 order_no/credential（防伪造已订）
    - 状态流转记录 booking.confirmed / booking.cancelled 事件
    """
    booking = await booking_service.update_booking_status(
        db, trip_id, booking_id, data, owner=user.id
    )
    return BookingOut.model_validate(booking)


@router.delete(
    "/{trip_id}/bookings/{booking_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除一条预订（owner，撤销误建建议）",
)
async def delete_trip_booking(
    trip_id: str,
    booking_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """owner 删除一条预订（撤销误建建议；受邀请只读不可删）。"""
    await booking_service.delete_booking(db, trip_id, booking_id, owner=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)