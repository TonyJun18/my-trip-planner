"""机票特价 API 测试：GET flight-deals / POST choice / DELETE choice / 权限与降级。

离线：注入 fake provider（注册表替换 tavily），所有价格来自 fixture 页面，
不打真实网络；DB 走 conftest 的测试库。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.services import flight_deals_service as fds


FIXTURES_OFFERS = [
    {
        "price": 1103.0, "currency": "CNY", "price_kind": "from",
        "airlines": ["北京首都航空", "中国东方航空"],
        "outbound_date": "2026-12-10", "inbound_date": "2026-12-17", "stops": 0,
        "source": "skyscanner", "source_url": "https://www.tianxun.com/routes/hgh/cctu/hangzhou-to-chengdu.html",
        "confidence": 0.8, "from_code": "HGH", "to_code": "CCTU",
    },
    {
        "price": 1123.0, "currency": "CNY", "price_kind": "from",
        "airlines": ["长龙航空"], "outbound_date": "2026-12-20", "inbound_date": "2026-12-27",
        "stops": 1, "source": "skyscanner",
        "source_url": "https://www.tianxun.com/routes/hgh/cctu/hangzhou-to-chengdu.html",
        "confidence": 0.8,
    },
    {
        "price": 1180.0, "currency": "CNY", "price_kind": "from",
        "airlines": ["四川航空"], "outbound_date": "2026-12-09", "inbound_date": "2026-12-16",
        "stops": 0, "source": "trip.com", "source_url": "https://www.trip.com/flights/hgh-ctu/",
        "confidence": 0.7,
    },
]


CALLS: list[int] = [0]


class _FakeProvider:
    name = "tavily"

    async def collect(self, request):
        CALLS[0] += 1
        return {
            "pages": [(
                "https://www.tianxun.com/routes/hgh/cctu/hangzhou-to-chengdu.html",
                "fixture-placeholder",
            )],
            "search": [{
                "title": "南航冬季机票大促 特价",
                "url": "https://www.csair.com/cn/promo",
                "content": "活动页摘要",
            }],
            "provider": "tavily",
        }


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch):
    """替换默认 provider，并对「页面解析」直接给结构化 offer。

    fake provider 走真实 service 组合逻辑（闸门/排序/缓存），只是不联网：
    用 monkeypatch 把 ``parse_offers`` 指向返回固定 offer 的实现即可。
    """
    fds.clear_memory_cache()
    CALLS[0] = 0
    monkeypatch.setitem(fds._PROVIDER_REGISTRY, "tavily", _FakeProvider())
    monkeypatch.setattr(fds, "parse_offers", lambda *a, **k: [dict(o) for o in FIXTURES_OFFERS])
    # fake provider 不返回 pages，parse 不会被调用；直接注入候选更直观
    yield
    fds.clear_memory_cache()


async def _make_trip(client, headers, *, departure: str | None = "杭州") -> str:
    resp = await client.post(
        "/api/v1/trips",
        json={
            "title": "机票测试", "destination": "成都", "departure": departure,
            "start_date": "2026-12-08", "end_date": "2026-12-15", "travelers": 2,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestFlightDealsAPI:
    async def test_get_returns_three_ranked_options(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        resp = await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "completed"
        assert data["price_kind"] == "from"
        assert 1 <= len(data["options"]) <= 3
        assert {o["strategy"] for o in data["options"]} == {"cheapest", "best_dates", "safest"}
        assert all(o["source_url"].startswith("http") for o in data["options"])
        assert data["note"] == fds.NOTE_DEFAULT
        assert data["selected"] is None

    async def test_second_get_hits_snapshot_cache(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)
        assert CALLS[0] == 1
        again = await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)
        assert again.status_code == 200
        assert again.json()["is_cached"] is True
        assert CALLS[0] == 1

    async def test_refresh_forces_recollect(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)
        forced = await client.get(
            f"/api/v1/trips/{trip_id}/flight-deals?refresh=1", headers=headers
        )
        assert forced.status_code == 200
        assert forced.json()["is_cached"] is False
        assert CALLS[0] == 2

    async def test_no_departure_returns_skipped(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers, departure=None)
        resp = await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        assert data["options"] == []

    async def test_other_user_gets_404(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        other = await client.post(
            "/api/v1/auth/register",
            json={"email": "flight-other@test.com", "password": "test1234", "display_name": "别人"},
        )
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        resp = await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=other_headers)
        assert resp.status_code == 404


class TestSnapshotCache:
    async def test_partial_snapshot_gets_short_ttl(self, client, auth_user, db_session, monkeypatch):
        """只有促销没有报价 → 快照 TTL 5min（避免一次抽取失败毒化 6h 缓存）。"""
        from sqlalchemy import select

        from app.models import FlightDealSnapshot

        class _PromoOnly:
            name = "tavily"

            async def collect(self, request):
                return {
                    "pages": [],
                    "search": [{
                        "title": "南航冬季机票大促",
                        "url": "https://www.csair.com/cn/promo",
                        "content": "特价活动",
                    }],
                    "provider": "tavily",
                }

        monkeypatch.setitem(fds._PROVIDER_REGISTRY, "tavily", _PromoOnly())
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        resp = await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "partial"
        assert resp.json()["options"] == []

        row = (await db_session.execute(select(FlightDealSnapshot))).scalars().first()
        assert row is not None
        ttl = (row.expires_at - row.fetched_at).total_seconds()
        assert ttl == fds.PARTIAL_CACHE_TTL_SECONDS


class TestFlightChoice:
    async def test_choose_option_writes_pending_booking(self, client, auth_user, db_session):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        deals = (await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)).json()
        option = deals["options"][0]

        resp = await client.post(
            f"/api/v1/trips/{trip_id}/flight-choice",
            json={"option_id": option["option_id"]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending"
        assert data["reference"] == "plan.generated"
        # 2 人 × 起价
        assert data["amount"] == pytest.approx(option["price"] * 2)
        assert data["currency"] == option["currency"]
        assert data["provider_url"] == option["source_url"]
        assert "2 人合计" in data["title"]

        # 已选状态可见
        after = (await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)).json()
        assert after["selected"] is not None
        assert after["selected_booking_id"] == data["booking_id"]

        # 预订列表里能查到（kind=flight）
        bookings = (await client.get(f"/api/v1/trips/{trip_id}/bookings", headers=headers)).json()
        assert any(b["kind"] == "flight" for b in bookings["items"])

    async def test_choose_is_idempotent(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        deals = (await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)).json()
        first = await client.post(
            f"/api/v1/trips/{trip_id}/flight-choice",
            json={"option_id": deals["options"][0]["option_id"]}, headers=headers,
        )
        second = await client.post(
            f"/api/v1/trips/{trip_id}/flight-choice",
            json={"option_id": deals["options"][1]["option_id"]}, headers=headers,
        )
        assert second.status_code == 200
        assert second.json()["booking_id"] == first.json()["booking_id"]
        assert second.json()["amount"] != first.json()["amount"]

        bookings = (await client.get(f"/api/v1/trips/{trip_id}/bookings", headers=headers)).json()
        assert len([b for b in bookings["items"] if b["kind"] == "flight"]) == 1

    async def test_unknown_option_id_is_400(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)
        resp = await client.post(
            f"/api/v1/trips/{trip_id}/flight-choice",
            json={"option_id": "fd_99"}, headers=headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "flight_choice_invalid"

    async def test_manual_option_requires_title_price_currency(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        bad = await client.post(
            f"/api/v1/trips/{trip_id}/flight-choice",
            json={"option": {"title": "自己找的航班"}}, headers=headers,
        )
        assert bad.status_code == 400

        ok = await client.post(
            f"/api/v1/trips/{trip_id}/flight-choice",
            json={"option": {"title": "自己找的航班", "price": 880, "currency": "CNY",
                             "source_url": "https://www.trip.com/flights/x"}},
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["amount"] == pytest.approx(880 * 2)

    async def test_clear_choice(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        deals = (await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)).json()
        await client.post(
            f"/api/v1/trips/{trip_id}/flight-choice",
            json={"option_id": deals["options"][0]["option_id"]}, headers=headers,
        )
        resp = await client.delete(f"/api/v1/trips/{trip_id}/flight-choice", headers=headers)
        assert resp.status_code == 204
        after = (await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)).json()
        assert after["selected"] is None
        # 再删一次 → 404（无选择）
        again = await client.delete(f"/api/v1/trips/{trip_id}/flight-choice", headers=headers)
        assert again.status_code == 404

    async def test_choice_emits_edit_event(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_trip(client, headers)
        deals = (await client.get(f"/api/v1/trips/{trip_id}/flight-deals", headers=headers)).json()
        await client.post(
            f"/api/v1/trips/{trip_id}/flight-choice",
            json={"option_id": deals["options"][0]["option_id"]}, headers=headers,
        )
        events = (await client.get(f"/api/v1/trips/{trip_id}/events", headers=headers)).json()
        items = events.get("items", events if isinstance(events, list) else [])
        assert any(
            e.get("event_type") == "edit" and (e.get("payload") or {}).get("kind") == "flight_choice"
            for e in items
        ), f"应记录 flight_choice 事件，实际: {items[:3]}"
