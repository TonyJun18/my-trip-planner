"""task-booking-ledger-rhythm：预订节奏规则库测试（booking-rhythm spec）。

覆盖：
1. 火车预售窗口（service_date - 15 天，phase: upcoming/open/closing）
2. 热门场馆放票窗口（故宫规则表命中 / timed-entry 通用档不编造放票时刻）
3. 机票关注窗口（T-30，无价格断言字段）
4. 酒店取消检查提醒（入住日 - 7 天）
5. 去重（confirmed 不再提醒 / pending 保留 / 同一目标至多一条）
6. 无副作用（签名无 db，重复调用结果相等）+ 诚实标注（basis + 以官方渠道为准）
7. API 端点（owner 专属 / 未登录 401 / 他人 404 / 两次读取稳定）

全部不依赖外部环境（内存 ORM / 纯规则，无 LLM/无网络）。
"""
from __future__ import annotations

import uuid
from datetime import date

from httpx import AsyncClient

from app.models import Stop, Trip, TripBooking, TripDay

TODAY = date(2026, 11, 10)


# ── 构造器 ───────────────────────────────────────────────────────
def _trip(*, with_stops: list[tuple[str, str, date]] | None = None) -> Trip:
    """内存 Trip（不落库）：with_stops = [(stop_name, stop_type, day_date), ...]。"""
    trip = Trip(
        owner="u-rhythm",
        title="节奏测试",
        destination="北京",
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 21),
        travelers=1,
    )
    days: dict[date, TripDay] = {}
    for name, stop_type, day_date in (with_stops or []):
        day = days.get(day_date)
        if day is None:
            day = TripDay(day_number=len(days) + 1, date=day_date)
            days[day_date] = day
            trip.days.append(day)
        day.stops.append(Stop(name=name, stop_type=stop_type, order_index=len(day.stops) + 1))
    return trip


def _booking(kind: str, *, service_date: date | None = None, status: str = "suggested",
             title: str | None = None) -> TripBooking:
    return TripBooking(
        trip_id="t", kind=kind, provider="12306" if kind == "train" else "ctrip",
        title=title or f"{kind}-title", status=status, reference="plan.generated",
        service_date=service_date,
    )


# ── 火车预售窗口 ─────────────────────────────────────────────────
class TestTrainPresale:
    def test_window_upcoming_before_release(self):
        """service_date=2026-12-01、today=2026-11-10 → window_open=2026-11-16、phase=upcoming。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("train", service_date=date(2026, 12, 1))], today=TODAY
        )
        trains = [i for i in items if i["kind"] == "train"]
        assert len(trains) == 1
        assert trains[0]["window_open"] == date(2026, 11, 16)  # 12-01 减 15 天
        assert trains[0]["phase"] == "upcoming"
        assert trains[0]["window_deadline"] == date(2026, 12, 1)

    def test_window_open_on_release_day(self):
        """today=2026-11-16（开售日）→ phase=open。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("train", service_date=date(2026, 12, 1))],
            today=date(2026, 11, 16),
        )
        trains = [i for i in items if i["kind"] == "train"]
        assert len(trains) == 1
        assert trains[0]["phase"] == "open"

    def test_closing_near_deadline(self):
        """发车日前 3 天内（窗口已开、临近截止）→ phase=closing。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("train", service_date=date(2026, 12, 1))],
            today=date(2026, 11, 29),
        )
        trains = [i for i in items if i["kind"] == "train"]
        assert len(trains) == 1
        assert trains[0]["phase"] == "closing"


# ── 热门场馆放票窗口 ─────────────────────────────────────────────
class TestVenueRelease:
    def test_gugong_named_rule(self):
        """站点名含「故宫」→ ticket 条目 window_open=游玩日-7、note 含具体放票时刻口径。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        trip = _trip(with_stops=[("故宫博物院", "attraction", date(2026, 11, 20))])
        items = compute_booking_rhythm(trip, [], today=TODAY)
        tickets = [i for i in items if i["kind"] == "ticket"]
        assert len(tickets) == 1
        assert tickets[0]["window_open"] == date(2026, 11, 13)  # 11-20 减 7 天
        assert tickets[0]["window_deadline"] == date(2026, 11, 20)
        assert "故宫" in tickets[0]["target"]

    def test_generic_timed_entry_no_fabricated_time(self):
        """未命中放票表但 timed-entry 命中（科技馆）→ 通用档提前 7 天，note 不含具体放票时刻。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        trip = _trip(with_stops=[("上海科技馆", "attraction", date(2026, 11, 20))])
        items = compute_booking_rhythm(trip, [], today=TODAY)
        tickets = [i for i in items if i["kind"] == "ticket"]
        assert len(tickets) == 1
        assert tickets[0]["window_open"] == date(2026, 11, 13)
        assert "20:00" not in tickets[0]["note"]  # 不编造具体放票时刻
        assert "7" in tickets[0]["note"]

    def test_same_stop_at_most_one(self):
        """同一站点（同日同名）去重 → 至多一条。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        trip = _trip(with_stops=[
            ("故宫博物院", "attraction", date(2026, 11, 20)),
            ("故宫博物院", "attraction", date(2026, 11, 20)),
        ])
        items = compute_booking_rhythm(trip, [], today=TODAY)
        assert len([i for i in items if i["kind"] == "ticket"]) == 1


# ── 机票关注窗口 / 酒店取消检查 ──────────────────────────────────
class TestFlightAndHotel:
    def test_flight_watch_window_no_price_assertion(self):
        """机票 service_date 未来 → 关注窗口条目；无任何价格断言字段。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("flight", service_date=date(2026, 12, 11),
                               title="MU5101 杭州→北京")], today=TODAY
        )
        flights = [i for i in items if i["kind"] == "flight"]
        assert len(flights) == 1
        assert flights[0]["window_open"] == date(2026, 11, 11)  # T-30
        assert flights[0]["window_deadline"] == date(2026, 12, 11)
        assert "price" not in flights[0]  # 无价格断言字段
        assert not any("price" in k.lower() for k in flights[0])
        assert "最低价" not in flights[0]["note"]

    def test_hotel_cancel_check_reminder(self):
        """酒店入住日-7 → 取消检查提醒条目。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("hotel", service_date=date(2026, 11, 20),
                               title="北京饭店")], today=TODAY
        )
        hotels = [i for i in items if i["kind"] == "hotel"]
        assert len(hotels) == 1
        assert hotels[0]["window_open"] == date(2026, 11, 13)  # 入住日 - 7
        assert "取消" in hotels[0]["note"]


# ── 去重 ─────────────────────────────────────────────────────────
class TestDedup:
    def test_confirmed_target_suppressed(self):
        """台账已 confirmed 的火车票 → 不再产出该目标节奏。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("train", service_date=date(2026, 12, 1), status="confirmed")],
            today=TODAY,
        )
        assert not [i for i in items if i["kind"] == "train"]

    def test_confirmed_wins_over_pending_same_target(self):
        """同目标既有 confirmed 又有 pending → confirmed 生效，整体不提醒。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [
                _booking("train", service_date=date(2026, 12, 1), status="confirmed"),
                _booking("train", service_date=date(2026, 12, 1), status="pending"),
            ], today=TODAY,
        )
        assert not [i for i in items if i["kind"] == "train"]

    def test_pending_target_kept(self):
        """pending（订了未确认）→ 保留节奏提醒（回填凭证确认）。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("train", service_date=date(2026, 12, 1), status="pending")],
            today=TODAY,
        )
        assert len([i for i in items if i["kind"] == "train"]) == 1

    def test_same_kind_date_at_most_one(self):
        """同 kind 同 service_date 两条 pending → 至多一条。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [
                _booking("train", service_date=date(2026, 12, 1), status="pending", title="G39"),
                _booking("train", service_date=date(2026, 12, 1), status="pending", title="G41"),
            ], today=TODAY,
        )
        assert len([i for i in items if i["kind"] == "train"]) == 1

    def test_cancelled_target_suppressed(self):
        """cancelled（已取消的旧条目）→ 不产出节奏。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("train", service_date=date(2026, 12, 1), status="cancelled")],
            today=TODAY,
        )
        assert not [i for i in items if i["kind"] == "train"]


# ── 无副作用 + 诚实标注 ──────────────────────────────────────────
class TestPurityAndHonesty:
    def test_repeated_calls_stable(self):
        """纯函数：同输入两次调用结果完全相等（签名无 db → 无写入路径）。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        trip = _trip(with_stops=[("故宫博物院", "attraction", date(2026, 11, 20))])
        bookings = [
            _booking("train", service_date=date(2026, 12, 1)),
            _booking("hotel", service_date=date(2026, 11, 20)),
        ]
        first = compute_booking_rhythm(trip, bookings, today=TODAY)
        second = compute_booking_rhythm(trip, bookings, today=TODAY)
        assert first == second

    def test_all_entries_rule_based_with_official_hint(self):
        """每条 basis=rule_based 且 note 含「以官方渠道为准」。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        trip = _trip(with_stops=[("故宫博物院", "attraction", date(2026, 11, 20))])
        bookings = [
            _booking("train", service_date=date(2026, 12, 1)),
            _booking("flight", service_date=date(2026, 12, 11)),
            _booking("hotel", service_date=date(2026, 11, 20)),
        ]
        items = compute_booking_rhythm(trip, bookings, today=TODAY)
        assert len(items) >= 4
        for i in items:
            assert i["basis"] == "rule_based"
            assert "以官方渠道为准" in i["note"]

    def test_expired_target_skipped(self):
        """目标日期已过（service_date < today）→ 不再提醒。"""
        from app.services.booking_rhythm import compute_booking_rhythm

        items = compute_booking_rhythm(
            _trip(), [_booking("train", service_date=date(2026, 11, 1))], today=TODAY
        )
        assert not [i for i in items if i["kind"] == "train"]


# ── API 端点 ─────────────────────────────────────────────────────
class TestRhythmEndpoint:
    async def test_rhythm_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/trips/00000000-0000-0000-0000-000000000000/bookings/rhythm")
        assert resp.status_code == 401

    async def test_rhythm_owner_only(self, client: AsyncClient, auth_user):
        """owner 可读且含节奏条目；他人 404。"""
        _user, headers = auth_user
        resp = await client.post("/api/v1/trips", headers=headers, json={
            "title": "节奏端点", "destination": "北京", "departure": "上海",
            "start_date": "2026-11-20", "end_date": "2026-11-21", "travelers": 1,
        })
        assert resp.status_code == 201, resp.text
        trip_id = resp.json()["id"]
        resp = await client.post(f"/api/v1/trips/{trip_id}/bookings", headers=headers, json={
            "kind": "train", "provider": "12306", "title": "杭州→北京 G39",
            "status": "suggested", "reference": "plan.generated",
            "service_date": "2026-12-01",
        })
        assert resp.status_code == 201, resp.text

        resp = await client.get(f"/api/v1/trips/{trip_id}/bookings/rhythm", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] >= 1
        assert any(i["kind"] == "train" for i in body["items"])

        # 两次读取结果稳定（派生读路径，无副作用）
        resp2 = await client.get(f"/api/v1/trips/{trip_id}/bookings/rhythm", headers=headers)
        assert resp2.json() == body

        # 他人 token → 404（行程不可见）
        resp = await client.post("/api/v1/auth/register", json={
            "email": f"rhythm-{uuid.uuid4().hex[:8]}@test.com",
            "password": "test1234", "display_name": "他人",
        })
        other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        resp = await client.get(f"/api/v1/trips/{trip_id}/bookings/rhythm", headers=other_headers)
        assert resp.status_code == 404
