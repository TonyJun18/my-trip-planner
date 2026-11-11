"""预订 API（task-booking-outlink：可预订建议 + 凭证回填 + 状态机；task-book-ahead-scan：前瞻扫描）。

端点（挂 /trips 前缀，路径字面量在 /{trip_id} 之前注册，避免路由吞参）：
- GET    /trips/{trip_id}/bookings           —— 预订列表（owner）
- POST   /trips/{trip_id}/bookings           —— 新增/回填一条预订（owner）
- POST   /trips/{trip_id}/bookings/scan      —— 预订前瞻扫描（owner，规则库零凭证）
- POST   /trips/{trip_id}/bookings/{booking_id}/status —— 更新状态（confirm/cancel）
- DELETE /trips/{trip_id}/bookings/{booking_id}        —— 删除（owner）
- POST   /trips/{trip_id}/bookings/{booking_id}/link   —— 回填确认号到站点（owner）
- DELETE /trips/{trip_id}/bookings/{booking_id}/link   —— 解除站点关联（owner）

与 expense 同信任语义：owner 可写；share/edit token 只读（在 trips_share 的
分享视图里只读展示预订状态，不暴露凭证号给只读链接持有者）。
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import (
    BookingIn,
    BookingListOut,
    BookingOut,
    BookingRhythmItemOut,
    BookingRhythmOut,
    BookingScanOut,
    BookingStatusIn,
    EmailMergeListIn,
    EmailMergeOut,
    StopLinkIn,
    StopOut,
    StopWriteOut,
)
from app.services import booking_service
from app.services.booking_rhythm import compute_booking_rhythm
from app.services.trip_service import get_trip

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
    outs: list[BookingOut] = []
    for b in items:
        out = BookingOut.model_validate(b)
        out.days_until = booking_service.booking_days_until(b)
        outs.append(out)
    return BookingListOut(
        items=outs,
        total=len(items),
    )


@router.post(
    "/{trip_id}/bookings/scan",
    response_model=BookingScanOut,
    summary="预订前瞻扫描（owner，规则库）",
)
async def scan_trip_bookings(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> BookingScanOut:
    """规则库扫描行程站点，标记值得提前预订的站点（Passage AI「Need tickets?」）。

    - 纯规则（timed-entry / 热门类目关键词 / 酒店），零凭证、零 LLM；
    - 只返回建议，不落库；前端「一键采纳」用 booking_payload 提交 POST /bookings。
    """
    from app.services.trip_service import get_trip

    trip = await get_trip(db, trip_id, owner=user.id)
    suggestions = booking_service.scan_bookable_stops(trip)
    items = []
    for s in suggestions:
        payload = {
            "kind": s["kind"],
            "provider": s["provider"],
            "title": s["title"],
            "status": "suggested",
            "reference": "plan.generated",
        }
        items.append({
            "stop_id": s["stop_id"],
            "stop_name": s["stop_name"],
            "kind": s["kind"],
            "provider": s["provider"],
            "title": s["title"],
            "reason": s["reason"],
            "priority": s["priority"],
            "timed_entry": s["timed_entry"],
            "booking_payload": payload,
        })
    return BookingScanOut(items=items, total=len(items))


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
    "/{trip_id}/bookings/merge-email",
    response_model=EmailMergeOut,
    summary="邮件预订条目归并台账（owner）",
)
async def merge_email_bookings(
    trip_id: str,
    data: EmailMergeListIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EmailMergeOut:
    """把邮件导入解析出的预订条目归并进台账（task-booking-ledger-rhythm）。

    - 解析是候选、落库是决定：一律 status=pending、reference=email.import，
      绝不采纳请求侧 status/credential（防伪造已订）；
    - 幂等：有码 provider+order_no；无码 em- 合成键；
    - kind 归一：flight/hotel/activity → flight/hotel/ticket。
    """
    merged = await booking_service.merge_email_bookings(
        db, trip_id, data.items, owner=user.id
    )
    out = [BookingOut.model_validate(b) for b in merged]
    return EmailMergeOut(merged=out, total=len(out))


@router.get(
    "/{trip_id}/bookings/rhythm",
    response_model=BookingRhythmOut,
    summary="预订节奏表（owner；确定性规则库实时计算，不落库）",
)
async def get_booking_rhythm(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> BookingRhythmOut:
    """「什么时候该订什么」的节奏表（task-booking-ledger-rhythm · D8/D9）。

    - 纯派生读路径：每次读取实时计算（签名级无写入路径），不落 trip_events、
      不依赖定时任务/推送；两次读取结果稳定；
    - 四类规则：火车预售 15 天 / 场馆放票（规则表+通用档）/ 机票 T-30 关注窗 /
      酒店入住前 7 天取消检查；每条 basis=rule_based 且提示以官方渠道为准；
    - 去重：confirmed 目标不再提醒；同目标至多一条。
    """
    trip = await get_trip(db, trip_id, owner=user.id)
    bookings = await booking_service.list_bookings(db, trip_id, owner=user.id)
    items = compute_booking_rhythm(trip, bookings, today=datetime.now(UTC).date())
    out = [BookingRhythmItemOut(**i) for i in items]
    return BookingRhythmOut(items=out, total=len(out))


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


# ── 确认号回填 stop（task-book-ahead-scan：Passage AI「Need tickets?」） ──
@router.post(
    "/{trip_id}/bookings/{booking_id}/link",
    response_model=StopWriteOut,
    summary="回填预订确认号到站点（owner）",
)
async def link_booking_to_stop(
    trip_id: str,
    booking_id: str,
    body: StopLinkIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StopWriteOut:
    """把预订条目挂到站点（stop.details.booking_id），确认号在站点级可见。

    - body: {"stop_id": "..."}；三路交叉校验（行程/预订/站点同属）；
    - 幂等：重复 link 自然覆盖。
    """
    stop = await booking_service.link_booking_to_stop(
        db, trip_id, booking_id, body.stop_id, owner=user.id
    )
    return StopWriteOut.model_validate(stop)


@router.delete(
    "/{trip_id}/bookings/{booking_id}/link",
    response_model=StopWriteOut,
    summary="解除预订与站点关联（owner）",
)
async def unlink_booking_from_stop(
    trip_id: str,
    booking_id: str,
    body: StopLinkIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StopWriteOut:
    """解除站点与预订的关联（移除 stop.details.booking_id；预订条目本身保留）。"""
    stop = await booking_service.unlink_booking_from_stop(
        db, trip_id, booking_id, body.stop_id, owner=user.id
    )
    return StopWriteOut.model_validate(stop)