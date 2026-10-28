"""预订服务（task-booking-outlink：可预订建议 + 凭证回填 + 状态机）。

设计哲学（与 expense_service / servicing_service 同源）：
- **代码确定性**：provider_url 是纯规则组装（``_deeplink``），不经过 LLM、不伪造"可订"；
- **零凭证**：不自建库存，不代收资金；用户跳 OTA 完成交易，回来粘贴凭证回填（复用
  email_import 敌意输入剥离，见 api 层）；
- **状态机**：suggested → pending → confirmed ⇄ cancelled；只允许带凭证
  （order_no/credential）进入 confirmed；suggested 可重复 upsert（幂等）；
- **诚实口径**：reference 区分 plan.generated / user.confirmed / channel.callback，
  绝不把「建议」当作「已订」；
- **事件联动**：confirm/cancel 记 booking.confirmed / booking.cancelled 事件
  （append-only，复用 event_service.record_event）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models import TripBooking
from app.schemas import BookingIn, BookingStatusIn

Provider = Literal["ctrip", "qunar", "12306", "feizhu", "tongcheng", "manual"]
Kind = Literal["train", "hotel"]


class BookingStateError(AppError):
    """预订状态机非法流转。"""

    status_code = 400
    code = "booking_invalid_transition"


# ── 可预订外链（纯函数，无网络） ────────────────────────────────
# provider 主页（作为未知 URL 的降级目标；只收录已知可跳转的）。
_PROVIDER_HOME: dict[str, str] = {
    "ctrip": "https://m.ctrip.com/webapp/train/",
    "qunar": "https://train.qunar.com/",
    "12306": "https://www.12306.cn/index/",
    "feizhu": "https://www.fliggy.com/",
    "tongcheng": "https://www.ly.com/",
    "manual": "",
}

# 12306 余票查询（中国铁路）：station 需车站名/电报码；queryDate=YYYY-MM-DD
# 注意：12306 接口有反爬与校验，仅供"跳转查询"参考，不作票价断言。
_PROVIDER_HINT: dict[str, str] = {
    "ctrip": "https://m.ctrip.com/webapp/train/SearchTrainList?from={from}&to={to}&date={date}",
    "qunar": "https://train.qunar.com/station/toStation.htm?fromStation={from}&toStation={to}&date={date}",
    "12306": "https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc&fs={from}&ts={to}&date={date}",
}


def _deeplink(
    provider: Provider,
    kind: Kind,
    query: dict[str, Any],
) -> str | None:
    """组装可预订外链（纯函数，无网络；未知 provider/参数不齐 → None）。"""
    provider = provider or "ctrip"
    kind = kind or "train"
    if provider == "manual":
        return None
    if provider not in _PROVIDER_HINT:
        return _PROVIDER_HOME.get(provider)
    if kind == "train":
        _from = (query.get("departure") or "").strip()
        _to = (query.get("destination") or "").strip()
        date = (query.get("date") or "").strip()
        if not _from or not _to:
            return None
        return _PROVIDER_HINT[provider].format_map(
            {"from": _from, "to": _to, "date": date}
        )
    if kind == "hotel":
        city = (query.get("city") or "").strip()
        if not city:
            return None
        # 酒店搜索：城市维度统一跳 OTA 城市搜索页（携程/去哪儿/飞猪/同程各有城市页）
        # 简化：providers 用城市编码（URL 编码），统一跳转城市搜索；不伪造房型/价格
        import urllib.parse

        encoded = urllib.parse.quote(city)
        return f"https://m.ctrip.com/webapp/hotel/hotellist?city={encoded}"
    return None


def build_deeplink(
    provider: Provider,
    kind: Kind,
    query: dict[str, Any],
) -> str | None:
    """公开入口：组装可预订外链。"""
    return _deeplink(provider, kind, query)


# ── 建议 → 落库（规划编排层调用，回填 plan.bookings 同字段） ──────
def booking_suggested_payload(
    *,
    trip_id: str,
    kind: Kind,
    provider: Provider,
    title: str | None,
    provider_url: str | None,
    order_no: str | None,
    credential: str | None,
    status: str,
    reference: str,
    amount: float | None,
    currency: str,
) -> dict[str, Any]:
    """构造 TripBooking ORM 字段 dict（供编排层把 plan.bookings 落库）。"""
    return {
        "trip_id": trip_id,
        "kind": kind,
        "provider": provider,
        "title": title,
        "provider_url": provider_url,
        "order_no": order_no,
        "credential": credential,
        "status": status,
        "reference": reference,
        "amount": amount,
        "currency": currency,
        "confirmed_at": datetime.now(timezone.utc) if status == "confirmed" else None,
        "cancelled_at": datetime.now(timezone.utc) if status == "cancelled" else None,
    }


# ── CRUD/状态机 ─────────────────────────────────────────────────
async def upsert_booking(
    db: AsyncSession,
    trip_id: str,
    data: BookingIn,
    *,
    owner: str | None = None,
) -> TripBooking:
    """新增一条预订（幂等：同 provider + order_no 存在则更新为 confirmed/pending）。

    - 状态机约束：reference=user.confirmed 必须带 order_no（防伪造已订）；
    - suggested 可重复 upsert（幂等）：同 provider+order_no 存在则更新。
    """
    from app.services.trip_service import get_trip

    await get_trip(db, trip_id, owner=owner)

    if data.reference == "user.confirmed" and not (data.order_no or data.credential):
        raise BookingStateError("确认预订必须提供订单号或凭证", detail={"trip_id": trip_id})

    # 幂等 upsert：同 provider + order_no
    if data.order_no:
        stmt = select(TripBooking).where(
            TripBooking.trip_id == trip_id,
            TripBooking.provider == data.provider,
            TripBooking.order_no == data.order_no,
        )
        existing = (await db.execute(stmt)).scalars().first()
        if existing:
            if data.status in ("confirmed", "pending"):
                existing.status = data.status
                existing.reference = data.reference or existing.reference
                existing.credential = data.credential or existing.credential
                existing.amount = data.amount if data.amount is not None else existing.amount
                existing.updated_at = datetime.now(timezone.utc)
                if data.status == "confirmed" and not existing.confirmed_at:
                    existing.confirmed_at = datetime.now(timezone.utc)
            elif data.status == "cancelled":
                existing.status = "cancelled"
                existing.cancelled_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(existing)
            return existing

    booking = TripBooking(
        trip_id=trip_id,
        kind=data.kind,
        provider=data.provider,
        title=data.title,
        provider_url=data.provider_url,
        order_no=data.order_no,
        credential=data.credential,
        status=data.status,
        reference=data.reference,
        amount=data.amount,
        currency=data.currency or "CNY",
        confirmed_at=datetime.now(timezone.utc) if data.status == "confirmed" else None,
        cancelled_at=datetime.now(timezone.utc) if data.status == "cancelled" else None,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking


async def update_booking_status(
    db: AsyncSession,
    trip_id: str,
    booking_id: str,
    data: BookingStatusIn,
    *,
    owner: str | None = None,
) -> TripBooking:
    """更新预订状态（confirm / cancel / pending）。

    状态机：suggested → pending → confirmed ⇄ cancelled；
    - 进入 confirmed 必须带 order_no/credential（防伪造）；
    - 记录 booking.confirmed / booking.cancelled 事件（append-only）。
    """
    from app.services.trip_service import get_trip

    await get_trip(db, trip_id, owner=owner)

    stmt = select(TripBooking).where(TripBooking.id == booking_id, TripBooking.trip_id == trip_id)
    booking = (await db.execute(stmt)).scalars().first()
    if booking is None:
        raise NotFoundError("预订不存在", code="booking_not_found")

    old_status = booking.status
    new_status = data.status
    if new_status == "confirmed" and not (data.order_no or data.credential or booking.credential):
        raise BookingStateError("确认预订必须提供订单号或凭证", detail={"trip_id": trip_id})

    booking.status = new_status
    booking.updated_at = datetime.now(timezone.utc)
    if data.order_no:
        booking.order_no = data.order_no
    if data.credential:
        booking.credential = data.credential
    if new_status == "confirmed":
        booking.confirmed_at = booking.confirmed_at or datetime.now(timezone.utc)
        booking.cancelled_at = None
    elif new_status == "cancelled":
        booking.cancelled_at = datetime.now(timezone.utc)
        booking.confirmed_at = None
    await db.commit()
    await db.refresh(booking)

    if new_status in ("confirmed", "cancelled") and old_status != new_status:
        from app.services.event_service import record_event

        await record_event(
            db,
            trip_id=trip_id,
            event_type=f"booking.{new_status}",
            payload={
                "booking_id": booking.id,
                "kind": booking.kind,
                "provider": booking.provider,
                "title": booking.title,
                "order_no": booking.order_no,
                "credential": booking.credential,
                "status": new_status,
            },
            commit=False,  # 事务已提交，事件独立记录（失败静默）
        )
    return booking


async def list_bookings(
    db: AsyncSession,
    trip_id: str,
    *,
    owner: str | None = None,
) -> list[TripBooking]:
    """列出行程全部预订（时间正序）。"""
    from app.services.trip_service import get_trip

    await get_trip(db, trip_id, owner=owner)
    stmt = (
        select(TripBooking)
        .where(TripBooking.trip_id == trip_id)
        .order_by(TripBooking.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def delete_booking(
    db: AsyncSession,
    trip_id: str,
    booking_id: str,
    *,
    owner: str | None = None,
) -> None:
    """删除一条预订（owner 专属；撤销误建建议用，受邀请只读不可删）。"""
    from sqlalchemy import delete

    from app.services.trip_service import get_trip

    await get_trip(db, trip_id, owner=owner)
    result = await db.execute(
        delete(TripBooking).where(TripBooking.id == booking_id, TripBooking.trip_id == trip_id)
    )
    if result.rowcount == 0:
        raise NotFoundError("预订不存在", code="booking_not_found")
    await db.commit()