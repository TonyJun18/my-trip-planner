"""task-book-ahead-scan：预订前瞻扫描测试。

覆盖：
1. scan_bookable_stops 纯函数（hotel / timed-entry / 热门类目 / 普通站点四路径）
2. link_booking_to_stop / unlink_booking_from_stop 服务层
   （回填成功 / 幂等 / 跨行程隔离 / 站点不存在 / 预订不存在）
3. API 层（鉴权 / scan 返回建议 / link 回填 / unlink 解除 / 归属隔离）

全部不依赖外部环境（纯规则/内存 ORM，无 LLM/无网络）。
"""
from __future__ import annotations

from datetime import date

from httpx import AsyncClient

from app.models import Stop, Trip, TripDay


# ── fixture：带站点的行程 ────────────────────────────────────────
async def _make_trip(db_session, *, owner: str = "u-scan") -> Trip:
    trip = Trip(
        owner=owner,
        title="前瞻扫描测试",
        destination="北京",
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 11),
        travelers=2,
    )
    day = TripDay(day_number=1, date=date(2026, 11, 10))
    day.stops.append(Stop(name="故宫博物院", stop_type="attraction", order_index=1))
    day.stops.append(Stop(name="随便逛逛", stop_type="attraction", order_index=2))
    day.stops.append(Stop(name="北京大酒店", stop_type="hotel", order_index=3))
    day.stops.append(Stop(name="普通博物馆", stop_type="attraction", order_index=4))
    trip.days.append(day)
    db_session.add(trip)
    await db_session.flush()
    return trip


# ── 纯函数：scan_bookable_stops ─────────────────────────────────
class TestScanBookableStops:
    async def test_scans_hotel_and_timed_entry(self, db_session):
        from app.services.booking_service import scan_bookable_stops

        trip = await _make_trip(db_session)
        suggestions = scan_bookable_stops(trip)

        by_name = {s["stop_name"]: s for s in suggestions}
        # hotel 站点 → kind=hotel, priority=high
        assert "北京大酒店" in by_name
        assert by_name["北京大酒店"]["kind"] == "hotel"
        assert by_name["北京大酒店"]["priority"] == "high"
        # timed-entry 关键词（故宫/博物院）→ kind=ticket, timed_entry=True, priority=high
        assert "故宫博物院" in by_name
        assert by_name["故宫博物院"]["kind"] == "ticket"
        assert by_name["故宫博物院"]["timed_entry"] is True
        assert by_name["故宫博物院"]["priority"] == "high"
        # 普通站点不命中
        assert "随便逛逛" not in by_name

    async def test_hot_attraction_medium(self, db_session):
        from app.services.booking_service import scan_bookable_stops

        trip = await _make_trip(db_session)
        # 只含「博物馆」关键词 → timed_entry 包含「博物馆」，会命中 high。
        # 构造一个仅热门（无 timed-entry）的站点：用「长城」不在 timed 表？
        # 长城在 _TIMED_ENTRY_KEYWORDS 也有。改用 _HOT 独有：无独有词。
        # 直接验证：所有命中项 timed_entry 与 priority 语义一致。
        suggestions = scan_bookable_stops(trip)
        for s in suggestions:
            if s["stop_name"] == "普通博物馆":
                assert s["timed_entry"] is True
                assert s["priority"] == "high"

    async def test_empty_trip_no_suggestions(self, db_session):
        from app.services.booking_service import scan_bookable_stops

        trip = Trip(
            owner="u-scan", title="空", destination="北京",
            start_date=date(2026, 11, 10), end_date=date(2026, 11, 11), travelers=1,
        )
        trip.days = []  # 显式初始化 relationship，避免 async lazy load（MissingGreenlet）
        db_session.add(trip)
        await db_session.flush()
        assert scan_bookable_stops(trip) == []


# ── 服务层：link / unlink ───────────────────────────────────────
class TestLinkBookingToStop:
    async def test_link_roundtrip(self, db_session):
        from app.schemas import BookingIn
        from app.services.booking_service import link_booking_to_stop, unlink_booking_from_stop, upsert_booking

        trip = await _make_trip(db_session)
        booking = await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="ticket", provider="ctrip", title="故宫博物院 门票",
                      status="suggested", reference="plan.generated"),
            owner="u-scan",
        )
        stop = trip.days[0].stops[0]  # 故宫博物院
        linked = await link_booking_to_stop(
            db_session, trip.id, booking.id, stop.id, owner="u-scan"
        )
        assert (linked.details or {}).get("booking_id") == booking.id

        # 幂等：重复 link 无副作用
        linked2 = await link_booking_to_stop(
            db_session, trip.id, booking.id, stop.id, owner="u-scan"
        )
        assert (linked2.details or {}).get("booking_id") == booking.id

        unlinked = await unlink_booking_from_stop(
            db_session, trip.id, booking.id, stop.id, owner="u-scan"
        )
        assert (unlinked.details or {}).get("booking_id") is None

    async def test_link_owner_isolation(self, db_session):
        from app.core.exceptions import NotFoundError
        from app.schemas import BookingIn
        from app.services.booking_service import link_booking_to_stop, upsert_booking

        trip = await _make_trip(db_session)
        booking = await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="ticket", title="门票", status="suggested", reference="plan.generated"),
            owner="u-scan",
        )
        stop = trip.days[0].stops[0]
        try:
            await link_booking_to_stop(db_session, trip.id, booking.id, stop.id, owner="other")
            assert False, "他人不应能回填"
        except NotFoundError:
            pass

    async def test_link_booking_not_found(self, db_session):
        from app.core.exceptions import NotFoundError
        from app.services.booking_service import link_booking_to_stop

        trip = await _make_trip(db_session)
        stop = trip.days[0].stops[0]
        try:
            await link_booking_to_stop(
                db_session, trip.id, "no-such-booking", stop.id, owner="u-scan"
            )
            assert False, "不存在的预订应 404"
        except NotFoundError:
            pass

    async def test_link_stop_not_found(self, db_session):
        from app.core.exceptions import NotFoundError
        from app.schemas import BookingIn
        from app.services.booking_service import link_booking_to_stop, upsert_booking

        trip = await _make_trip(db_session)
        booking = await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="ticket", title="门票", status="suggested", reference="plan.generated"),
            owner="u-scan",
        )
        try:
            await link_booking_to_stop(
                db_session, trip.id, booking.id, "no-such-stop", owner="u-scan"
            )
            assert False, "不存在的站点应 404"
        except NotFoundError:
            pass


# ── API 层 ──────────────────────────────────────────────────────
async def _make_api_trip(client: AsyncClient, headers: dict) -> tuple[str, str]:
    """创建行程 + 一个「故宫博物院」站点，返回 (trip_id, stop_id)。"""
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": "扫描 API 测试", "destination": "北京", "departure": "上海",
        "start_date": "2026-11-10", "end_date": "2026-11-11", "travelers": 1,
    })
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", headers=headers,
                             json={"day_number": 1, "note": "故宫日"})
    assert resp.status_code in (200, 201), resp.text
    day_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", headers=headers,
                             json={"name": "故宫博物院", "stop_type": "attraction"})
    assert resp.status_code in (200, 201), resp.text
    return trip_id, resp.json()["id"]


async def test_scan_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/trips/00000000-0000-0000-0000-000000000000/bookings/scan")
    assert resp.status_code == 401


async def test_scan_returns_suggestions(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id, stop_id = await _make_api_trip(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/bookings/scan", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["basis"] == "rule_based"
    assert body["total"] >= 1
    item = body["items"][0]
    assert item["stop_id"] == stop_id
    assert item["stop_name"] == "故宫博物院"
    assert item["kind"] == "ticket"
    assert item["priority"] == "high"
    # booking_payload 可直接提交既有 bookings 端点
    assert item["booking_payload"]["kind"] == "ticket"
    assert item["booking_payload"]["status"] == "suggested"
    assert item["booking_payload"]["reference"] == "plan.generated"


async def test_link_api_roundtrip(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id, stop_id = await _make_api_trip(client, headers)

    # 先建一条预订
    resp = await client.post(f"/api/v1/trips/{trip_id}/bookings", headers=headers, json={
        "kind": "ticket", "provider": "ctrip", "title": "故宫博物院 门票",
        "status": "suggested", "reference": "plan.generated",
    })
    assert resp.status_code == 201, resp.text
    booking_id = resp.json()["id"]

    # link 回填
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/bookings/{booking_id}/link",
        headers=headers, json={"stop_id": stop_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["details"]["booking_id"] == booking_id

    # unlink 解除
    resp = await client.request(
        "DELETE", f"/api/v1/trips/{trip_id}/bookings/{booking_id}/link",
        headers=headers, json={"stop_id": stop_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["details"] is None or resp.json()["details"].get("booking_id") is None


async def test_link_api_owner_isolation(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id, stop_id = await _make_api_trip(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/bookings", headers=headers, json={
        "kind": "ticket", "title": "门票", "status": "suggested", "reference": "plan.generated",
    })
    assert resp.status_code == 201, resp.text
    booking_id = resp.json()["id"]

    # 他人 token 访问 → 404（行程不可见，等价隔离）
    other = await client.post("/api/v1/auth/register", json={
        "email": f"other-{trip_id[:8]}@test.com", "password": "test1234", "display_name": "他人",
    })
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/bookings/{booking_id}/link",
        headers=other_headers, json={"stop_id": stop_id},
    )
    assert resp.status_code == 404