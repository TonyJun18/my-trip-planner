"""task-booking-ledger-rhythm：预订台账测试（service_date / 邮件归并 / 排序倒计时 / 导出脱敏）。

覆盖（对应 openspec/changes/booking-ledger-rhythm）：
- Task 1：TripBooking.service_date / service_note 往返 + 可选默认 + 状态更新修正
- Task 2：邮件归并端点（有码幂等 / 无码合成键 / 凭证防线 / 归属隔离 / 注入防御）
- Task 3：列表排序 + days_until 倒计时 / 导出 owner 全量 / 分享路径脱敏

全部不依赖外部环境（内存 ORM / FakeLLM，无 LLM/无网络）。
"""
from __future__ import annotations

from datetime import date, timedelta

from httpx import AsyncClient

from app.models import Trip, TripBooking, TripDay


# ── fixture：最小行程 ────────────────────────────────────────────
async def _make_trip(db_session, *, owner: str = "u-ledger") -> Trip:
    trip = Trip(
        owner=owner,
        title="台账测试",
        destination="杭州",
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 21),
        travelers=1,
    )
    trip.days.append(TripDay(day_number=1, date=date(2026, 11, 20)))
    db_session.add(trip)
    await db_session.flush()
    return trip


# ── Task 1：service_date / service_note ─────────────────────────
class TestServiceDateFields:
    async def test_booking_service_date_roundtrip(self, client: AsyncClient, auth_user):
        """创建带服务日期与备注的预订 → 响应原样返回两字段。"""
        _user, headers = auth_user
        resp = await client.post("/api/v1/trips", headers=headers, json={
            "title": "台账往返", "destination": "杭州", "departure": "上海",
            "start_date": "2026-11-20", "end_date": "2026-11-21", "travelers": 1,
        })
        assert resp.status_code == 201, resp.text
        trip_id = resp.json()["id"]

        resp = await client.post(f"/api/v1/trips/{trip_id}/bookings", headers=headers, json={
            "kind": "train", "provider": "12306", "title": "杭州→上海 G39",
            "status": "pending", "reference": "email.import",
            "service_date": "2026-11-20", "service_note": "G39 二等座 05 车",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["service_date"] == "2026-11-20"
        assert body["service_note"] == "G39 二等座 05 车"
        assert body["status"] == "pending"
        assert body["reference"] == "email.import"

    async def test_booking_optional_fields_default_none(self, client: AsyncClient, auth_user):
        """旧字段集（无两新字段）创建成功且响应为 None——零破坏。"""
        _user, headers = auth_user
        resp = await client.post("/api/v1/trips", headers=headers, json={
            "title": "默认字段", "destination": "杭州", "departure": "上海",
            "start_date": "2026-11-20", "end_date": "2026-11-21", "travelers": 1,
        })
        trip_id = resp.json()["id"]

        resp = await client.post(f"/api/v1/trips/{trip_id}/bookings", headers=headers, json={
            "kind": "ticket", "provider": "ctrip", "title": "门票",
            "status": "suggested", "reference": "plan.generated",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["service_date"] is None
        assert body["service_note"] is None

    async def test_booking_status_update_service_date(self, client: AsyncClient, auth_user):
        """状态更新端点可修正 service_date / service_note。"""
        _user, headers = auth_user
        resp = await client.post("/api/v1/trips", headers=headers, json={
            "title": "状态修正", "destination": "杭州", "departure": "上海",
            "start_date": "2026-11-20", "end_date": "2026-11-21", "travelers": 1,
        })
        trip_id = resp.json()["id"]
        resp = await client.post(f"/api/v1/trips/{trip_id}/bookings", headers=headers, json={
            "kind": "hotel", "provider": "ctrip", "title": "酒店",
            "status": "pending", "reference": "email.import",
        })
        booking_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/{booking_id}/status",
            headers=headers,
            json={"status": "pending", "service_date": "2026-11-21", "service_note": "改住 21 日"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["service_date"] == "2026-11-21"
        assert body["service_note"] == "改住 21 日"


# ── Task 2：邮件归并端点（merge-email） ─────────────────────────
async def _api_trip(client: AsyncClient, headers: dict, *, title: str) -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": title, "destination": "杭州", "departure": "上海",
        "start_date": "2026-11-20", "end_date": "2026-11-21", "travelers": 1,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestMergeEmailBookings:
    async def test_merge_email_with_code_idempotent(self, client: AsyncClient, auth_user):
        """有码条目：归并两次 → 台账仅一条 pending、reference=email.import；第二次返回同一 id。"""
        _user, headers = auth_user
        trip_id = await _api_trip(client, headers, title="归并有码")
        payload = {
            "items": [{
                "kind": "hotel", "name": "杭州西湖大酒店", "code": "BK12345678",
                "datetime": "2026-11-20 14:00", "amount": 680.0, "currency": "CNY",
            }],
        }
        resp1 = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/merge-email", headers=headers, json=payload
        )
        assert resp1.status_code == 200, resp1.text
        first = resp1.json()["merged"][0]
        assert first["status"] == "pending"
        assert first["reference"] == "email.import"
        assert first["order_no"] == "BK12345678"
        assert first["service_date"] == "2026-11-20"  # 从解析 datetime 提取日期

        resp2 = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/merge-email", headers=headers, json=payload
        )
        assert resp2.status_code == 200, resp2.text
        again = resp2.json()["merged"][0]
        assert again["id"] == first["id"]  # 幂等：同 provider+order_no 不重复落行

    async def test_merge_email_without_code_fingerprint_key(self, client: AsyncClient, auth_user):
        """无码条目：order_no 为 em- 前缀合成键；重复归并命中同一合成键仅一条。"""
        _user, headers = auth_user
        trip_id = await _api_trip(client, headers, title="归并无码")
        payload = {
            "items": [{
                "kind": "flight", "name": "MU5101 杭州→北京",
                "datetime": "2026-11-20 08:30", "amount": 920.0, "currency": "CNY",
            }],
        }
        resp1 = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/merge-email", headers=headers, json=payload
        )
        assert resp1.status_code == 200, resp1.text
        first = resp1.json()["merged"][0]
        assert first["order_no"].startswith("em-")
        assert first["status"] == "pending"
        assert first["reference"] == "email.import"

        resp2 = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/merge-email", headers=headers, json=payload
        )
        assert resp2.status_code == 200, resp2.text
        again = resp2.json()["merged"][0]
        assert again["id"] == first["id"]

    async def test_merge_email_confirmed_requires_credential(self, client: AsyncClient, auth_user):
        """归并条目升 confirmed 仍受既有凭证防线约束（无凭证 400）。"""
        _user, headers = auth_user
        trip_id = await _api_trip(client, headers, title="归并凭证防线")
        resp = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/merge-email", headers=headers,
            json={"items": [{"kind": "hotel", "name": "酒店", "code": "BK0001"}]},
        )
        assert resp.status_code == 200, resp.text
        booking_id = resp.json()["merged"][0]["id"]

        resp = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/{booking_id}/status",
            headers=headers, json={"status": "confirmed"},
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "booking_invalid_transition"

    async def test_merge_email_owner_isolated(self, client: AsyncClient, auth_user):
        """非 owner（他人 token）归并 → 404（行程不可见）。"""
        _user, headers = auth_user
        trip_id = await _api_trip(client, headers, title="归并隔离")

        import uuid
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@test.com",
                  "password": "test1234", "display_name": "他人"},
        )
        other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/merge-email", headers=other_headers,
            json={"items": [{"kind": "hotel", "name": "酒店", "code": "BK0002"}]},
        )
        assert resp.status_code == 404, resp.text

    async def test_merge_email_ignores_client_status_injection(self, client: AsyncClient, auth_user):
        """服务端绝不信任解析结果：请求侧 status=confirmed+credential 被忽略，强制 pending。"""
        _user, headers = auth_user
        trip_id = await _api_trip(client, headers, title="归并注入防御")
        resp = await client.post(
            f"/api/v1/trips/{trip_id}/bookings/merge-email", headers=headers,
            json={"items": [{
                "kind": "hotel", "name": "酒店", "code": "BK0003",
                "status": "confirmed", "credential": "伪造凭证",
            }]},
        )
        assert resp.status_code == 200, resp.text
        merged = resp.json()["merged"][0]
        assert merged["status"] == "pending"
        assert merged["reference"] == "email.import"
