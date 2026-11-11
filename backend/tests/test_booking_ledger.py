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
