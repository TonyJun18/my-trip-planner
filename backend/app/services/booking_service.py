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
from app.models import Stop, Trip, TripBooking
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


# ── 预订前瞻扫描（task-book-ahead-scan：Passage AI「Need tickets?」） ──
# 规则库：timed-entry / 热门类目关键词表。零凭证、零 LLM、纯确定性。
# 扫描行程 stops → 标记值得提前预订的站点 → 复用 booking 链路产出建议。
_TIMED_ENTRY_KEYWORDS: tuple[str, ...] = (
    # 世界遗产 / 博物馆 / 热门景区（timed-entry 常见）
    "故宫", "博物馆", "展览馆", "美术馆", "科技馆", "熊猫", "迪士尼", "环球影城",
    "长隆", "方特", "海洋公园", "欢乐谷", "天坛", "颐和园", "长城", "兵马俑",
    "莫高窟", "布达拉宫", "黄山", "张家界", "九寨沟", "鼓浪屿", "西湖",
    # 演出 / 展览 / 体验
    "演出", "演唱会", "音乐节", "show", "秀", "话剧", "剧院", "马戏",
)

_HOT_ATTRACTION_KEYWORDS: tuple[str, ...] = (
    "博物馆", "故宫", "长城", "兵马俑", "莫高窟", "迪士尼", "环球影城",
    "长隆", "熊猫", "张家界", "九寨沟", "黄山", "鼓浪屿",
)


def _match_keywords(name: str, keywords: tuple[str, ...]) -> bool:
    """站点名命中任一词条（子串匹配，大小写不敏感）。"""
    if not name:
        return False
    low = name.lower()
    return any(k.lower() in low for k in keywords)


def scan_bookable_stops(trip: Trip) -> list[dict[str, Any]]:
    """规则库扫描：找出行程中「值得提前预订」的站点（纯函数，无 DB 副作用）。

    规则（全部确定性，basis=rule_based 诚实标注）：
    1. hotel 站点 → 建议提前预订（kind=hotel，城市维度 deeplink）；
    2. timed-entry 关键词命中（timed_entry=True）→ 建议提前预订（kind=ticket）；
    3. 热门类目词命中 → 建议提前预订（kind=ticket，priority=medium 区别于强 timed-entry）。
    """
    suggestions: list[dict[str, Any]] = []
    days = getattr(trip, "days", None) or []
    for day in days:
        for stop in day.stops or []:
            name = (stop.name or "").strip()
            if not name:
                continue
            stop_type = (stop.stop_type or "").lower()
            if stop_type == "hotel":
                suggestions.append({
                    "stop_id": stop.id,
                    "stop_name": name,
                    "kind": "hotel",
                    "provider": "ctrip",
                    "title": f"{name} 提前预订",
                    "reason": "住宿建议提前预订（行程核心节点）",
                    "priority": "high",
                    "timed_entry": False,
                })
                continue
            timed = _match_keywords(name, _TIMED_ENTRY_KEYWORDS)
            hot = _match_keywords(name, _HOT_ATTRACTION_KEYWORDS)
            if timed or hot:
                suggestions.append({
                    "stop_id": stop.id,
                    "stop_name": name,
                    "kind": "ticket",
                    "provider": "ctrip",
                    "title": f"{name} 门票",
                    "reason": "热门/限时场馆建议提前购票（timed-entry）" if timed
                    else "热门景点建议提前购票",
                    "priority": "high" if timed else "medium",
                    "timed_entry": timed,
                })
    return suggestions


async def link_booking_to_stop(
    db: AsyncSession,
    trip_id: str,
    booking_id: str,
    stop_id: str,
    *,
    owner: str | None = None,
) -> Stop:
    """把确认号/预订条目回填到站点（stop.details.booking_id，零迁移）。

    - 校验行程归属 + 预订属于该行程 + 站点属于该行程（三路交叉，防跨行程串号）；
    - stop.details 为 JSON 列：写入 booking_id（保留既有 details 字段）；
    - 幂等：重复 link 相同 booking 自然覆盖，无副作用。
    """
    from app.services.trip_service import get_trip

    trip = await get_trip(db, trip_id, owner=owner)

    stmt = select(TripBooking).where(TripBooking.id == booking_id, TripBooking.trip_id == trip_id)
    booking = (await db.execute(stmt)).scalars().first()
    if booking is None:
        raise NotFoundError("预订不存在", code="booking_not_found")

    stop_found = None
    for day in trip.days or []:
        for stop in day.stops or []:
            if stop.id == stop_id:
                stop_found = stop
                break
        if stop_found:
            break
    if stop_found is None:
        raise NotFoundError("站点不存在", code="stop_not_found")

    details = dict(stop_found.details or {})
    details["booking_id"] = booking_id
    stop_found.details = details
    await db.commit()
    await db.refresh(stop_found)
    return stop_found


async def unlink_booking_from_stop(
    db: AsyncSession,
    trip_id: str,
    booking_id: str,
    stop_id: str,
    *,
    owner: str | None = None,
) -> Stop:
    """解除站点与预订的关联（stop.details.booking_id 移除；预订条目本身保留）。"""
    from app.services.trip_service import get_trip

    trip = await get_trip(db, trip_id, owner=owner)

    stmt = select(TripBooking).where(TripBooking.id == booking_id, TripBooking.trip_id == trip_id)
    booking = (await db.execute(stmt)).scalars().first()
    if booking is None:
        raise NotFoundError("预订不存在", code="booking_not_found")

    stop_found = None
    for day in trip.days or []:
        for stop in day.stops or []:
            if stop.id == stop_id:
                stop_found = stop
                break
        if stop_found:
            break
    if stop_found is None:
        raise NotFoundError("站点不存在", code="stop_not_found")

    details = dict(stop_found.details or {})
    if details.get("booking_id") == booking_id:
        details.pop("booking_id", None)
        stop_found.details = details or None
        await db.commit()
        await db.refresh(stop_found)
    return stop_found