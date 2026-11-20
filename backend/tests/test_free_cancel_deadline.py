"""free-cancel-deadline 测试（task-free-cancel-deadline-eval）。

覆盖（对齐 openspec/changes/2026-11-20-free-cancel-deadline/spec.md）：
1. TripBooking.free_cancel_deadline 字段 roundtrip（创建/省略零破坏）
2. cancel_deadline_days 倒计时（+N / 无 deadline → null）
3. scan_cancel_deadline_reminders 纯函数四路径
   （窗口内产出 / 幂等不重复 / 已截止不产出 / 无截止日不产出）
4. EVENT_TYPES 注册 booking.cancel_deadline（顺带 booking.confirmed / booking.cancelled）
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import TripBooking, TripEvent


async def _create_trip(client, auth_headers) -> str:
    resp = await client.post(
        "/api/v1/trips",
        json={
            "title": "测试行程",
            "destination": "杭州",
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── 1. 字段 roundtrip ─────────────────────────────────────────

async def test_booking_free_cancel_deadline_roundtrip(client, auth_user):
    """创建预订带 free_cancel_deadline → 响应含该字段。"""
    _, headers = auth_user
    trip_id = await _create_trip(client, headers)

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/bookings",
        json={
            "kind": "hotel",
            "provider": "ctrip",
            "title": "西湖假日酒店",
            "status": "pending",
            "reference": "plan.generated",
            "free_cancel_deadline": "2026-12-01",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["free_cancel_deadline"] == "2026-12-01"
    # 未提供 order_no/credential 也能 pending（状态机不变）
    assert data["status"] == "pending"


async def test_booking_free_cancel_deadline_omitted_ok(client, auth_user):
    """旧客户端省略 free_cancel_deadline → 成功且为 None。"""
    _, headers = auth_user
    trip_id = await _create_trip(client, headers)

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/bookings",
        json={"kind": "train", "provider": "12306", "title": "G39", "status": "pending", "reference": "plan.generated"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["free_cancel_deadline"] is None


# ── 2. cancel_deadline_days 倒计时 ─────────────────────────────

async def test_booking_list_cancel_deadline_days(client, auth_user):
    """台账列表含 cancel_deadline_days：+3 → 3；无 → null。"""
    _, headers = auth_user
    trip_id = await _create_trip(client, headers)

    future = (date.today() + timedelta(days=3)).isoformat()
    await client.post(
        f"/api/v1/trips/{trip_id}/bookings",
        json={
            "kind": "hotel",
            "provider": "ctrip",
            "title": "A酒店",
            "status": "pending",
            "reference": "plan.generated",
            "free_cancel_deadline": future,
        },
        headers=headers,
    )
    await client.post(
        f"/api/v1/trips/{trip_id}/bookings",
        json={"kind": "train", "provider": "12306", "title": "G39", "status": "pending", "reference": "plan.generated"},
        headers=headers,
    )

    resp = await client.get(f"/api/v1/trips/{trip_id}/bookings", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    by_title = {b["title"]: b for b in items}
    assert by_title["A酒店"]["cancel_deadline_days"] == 3
    assert by_title["G39"]["cancel_deadline_days"] is None


# ── 3. 截止前提醒纯函数四路径 ─────────────────────────────────

def _mk_booking(deadline: date | None = None, status: str = "pending") -> TripBooking:
    b = TripBooking(
        id="b1",
        trip_id="t1",
        kind="hotel",
        provider="ctrip",
        title="A酒店",
        status=status,
        free_cancel_deadline=deadline,
    )
    return b


async def test_scan_reminders_window_hit(db_session):
    """窗口内（deadline ∈ (today, today+3]）→ 产出提醒条目。"""
    from app.services.booking_service import scan_cancel_deadline_reminders

    today = date(2026, 11, 20)
    b = _mk_booking(deadline=today + timedelta(days=2))
    out = scan_cancel_deadline_reminders([b], today=today)
    assert out == [
        {
            "booking_id": "b1",
            "title": "A酒店",
            "deadline": (today + timedelta(days=2)).isoformat(),
            "days_left": 2,
        }
    ]


async def test_scan_reminders_idempotent(db_session):
    """同一窗口重复扫描 → 只产出一条（幂等）。"""
    from app.services.booking_service import scan_cancel_deadline_reminders

    today = date(2026, 11, 20)
    b = _mk_booking(deadline=today + timedelta(days=1))
    first = scan_cancel_deadline_reminders([b], today=today, already_reminded={"b1"})
    assert first == []  # 已提醒标记 → 不再产出


async def test_scan_reminders_expired_silent(db_session):
    """已截止（deadline ≤ today）→ 不产出。"""
    from app.services.booking_service import scan_cancel_deadline_reminders

    today = date(2026, 11, 20)
    b = _mk_booking(deadline=today - timedelta(days=1))
    assert scan_cancel_deadline_reminders([b], today=today) == []


async def test_scan_reminders_null_silent(db_session):
    """无 deadline → 不产出（绝不编造）。"""
    from app.services.booking_service import scan_cancel_deadline_reminders

    today = date(2026, 11, 20)
    b = _mk_booking(deadline=None)
    assert scan_cancel_deadline_reminders([b], today=today) == []


async def test_scan_reminders_cancelled_silent(db_session):
    """已取消的条目 → 不产出提醒。"""
    from app.services.booking_service import scan_cancel_deadline_reminders

    today = date(2026, 11, 20)
    b = _mk_booking(deadline=today + timedelta(days=1), status="cancelled")
    assert scan_cancel_deadline_reminders([b], today=today) == []


# ── 4. 事件类型注册 ──────────────────────────────────────────

async def test_event_types_registered(db_session):
    """EVENT_TYPES 含 booking.cancel_deadline / confirmed / cancelled（消除历史 warning）。"""
    from app.services.event_service import EVENT_TYPES

    assert "booking.cancel_deadline" in EVENT_TYPES
    assert "booking.confirmed" in EVENT_TYPES
    assert "booking.cancelled" in EVENT_TYPES


async def test_booking_confirm_emits_event_no_warning(client, auth_user, db_session):
    """确认预订 → booking.confirmed 事件落库（类型已注册，无 warning）。"""
    _, headers = auth_user
    trip_id = await _create_trip(client, headers)
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/bookings",
        json={
            "kind": "hotel",
            "provider": "ctrip",
            "title": "A酒店",
            "status": "pending",
            "reference": "plan.generated",
            "free_cancel_deadline": (date.today() + timedelta(days=3)).isoformat(),
        },
        headers=headers,
    )
    bid = resp.json()["id"]
    await client.post(
        f"/api/v1/trips/{trip_id}/bookings/{bid}/status",
        json={"status": "confirmed", "order_no": "BK123", "credential": "cred-1"},
        headers=headers,
    )
    stmt = select(TripEvent).where(TripEvent.trip_id == trip_id)
    events = list((await db_session.execute(stmt)).scalars().all())
    types = [e.event_type for e in events]
    assert "booking.confirmed" in types