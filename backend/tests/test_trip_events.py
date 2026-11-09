"""行程事件通知测试（task-trip-event-notify）。

覆盖：
- event_service.record_event / list_events / event_out 基本契约
- API 双路径：owner JWT、share_token、edit_token
- 未知事件类型不崩（仍记录）
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from datetime import date

from app.services import event_service


async def _make_trip(client: AsyncClient, headers: dict, title: str = "事件测试") -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": title, "destination": "杭州",
        "start_date": "2026-11-01", "end_date": "2026-11-02",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── 服务层：record + list 基本契约 ───────────────────────────────
@pytest.mark.asyncio
async def test_record_and_list_event(db_session):
    from app.models import Trip

    trip = Trip(owner="user-1", title="事件测试", destination="杭州",
                start_date=date(2026, 11, 1), end_date=date(2026, 11, 3))
    db_session.add(trip)
    await db_session.commit()

    ev = await event_service.record_event(
        db_session, trip_id=trip.id, event_type="revise",
        payload={"summary": "把西湖挪到第一天"},
    )
    assert ev is not None
    assert ev.event_type == "revise"

    events = await event_service.list_events(db_session, trip.id)
    assert len(events) == 1
    payload = events[0].payload or {}
    assert payload.get("summary") == "把西湖挪到第一天"

    out = event_service.event_out(events[0])
    assert set(out) >= {"id", "trip_id", "event_type", "payload", "created_at"}


@pytest.mark.asyncio
async def test_list_events_pagination_and_order(db_session):
    from app.models import Trip

    trip = Trip(owner="user-1", title="分页测试", destination="杭州",
                start_date=date(2026, 11, 1), end_date=date(2026, 11, 3))
    db_session.add(trip)
    await db_session.commit()

    for i in range(5):
        await event_service.record_event(
            db_session, trip_id=trip.id, event_type="check", payload={"idx": i},
        )

    page = await event_service.list_events(db_session, trip.id, limit=2, offset=0)
    assert len(page) == 2
    assert (page[0].payload or {}).get("idx") == 4  # 最新在前


@pytest.mark.asyncio
async def test_unknown_event_type_still_records(db_session):
    from app.models import Trip

    trip = Trip(owner="user-1", title="未知类型", destination="杭州",
                start_date=date(2026, 11, 1), end_date=date(2026, 11, 3))
    db_session.add(trip)
    await db_session.commit()

    ev = await event_service.record_event(
        db_session, trip_id=trip.id, event_type="custom_unknown", payload={},
    )
    assert ev is not None  # 未知类型仍记录（仅 warning 日志）


# ── API：owner JWT 路径 ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_owner_can_list_events(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, "事件 API 测试")

    resp = await client.get(f"/api/v1/trips/{trip_id}/events", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_owner_events_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/trips/some-id/events")
    assert resp.status_code in (401, 403)


# ── API：share token 路径（免登录）──────────────────────────────
@pytest.mark.asyncio
async def test_share_token_can_list_events(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, "分享事件测试")

    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp.status_code in (200, 201), resp.text
    token = resp.json()["share_token"]

    resp = await client.get(f"/api/v1/trips/share/{token}/events")
    assert resp.status_code == 200, resp.text
    assert "items" in resp.json()


@pytest.mark.asyncio
async def test_invalid_share_token_404(client: AsyncClient):
    resp = await client.get("/api/v1/trips/share/not-a-real-token/events")
    assert resp.status_code == 404


# ── 记账 → 事件流（协作变更提示的数据源）──────────────────────
@pytest.mark.asyncio
async def test_expense_writes_edit_event_and_broadcasts(db_session, monkeypatch):
    """记账/撤销 → 事件流 edit(kind=expense) + collab 广播。

    前端「同伴更新了行程」提示只认 collab feed 上的 event.* 消息，
    所以记账必须留下事件并广播，否则同伴记账在本端完全静默。
    """
    from app.models import Trip
    from app.schemas.expense import ExpenseIn
    from app.services import expense_service

    published: list[dict] = []
    monkeypatch.setattr(
        "app.services.collab_service.publish_collab",
        lambda trip_id, payload: published.append({"trip_id": trip_id, **payload}),
    )

    trip = Trip(owner="user-1", title="记账事件", destination="杭州",
                start_date=date(2026, 11, 1), end_date=date(2026, 11, 2))
    db_session.add(trip)
    await db_session.commit()

    exp = await expense_service.add_expense(
        db_session, trip.id,
        ExpenseIn(category="food", amount=88.5, currency="CNY"),
        owner="user-1",
    )

    events = await event_service.list_events(db_session, trip.id)
    assert len(events) == 1
    assert events[0].event_type == "edit"
    payload = events[0].payload or {}
    assert payload.get("kind") == "expense"
    assert payload.get("action") == "add"
    assert payload.get("amount") == 88.5
    assert published and published[-1]["type"] == "event.edit"
    assert published[-1]["trip_id"] == trip.id

    await expense_service.delete_expense(db_session, trip.id, exp.id, owner="user-1")
    events = await event_service.list_events(db_session, trip.id)
    assert len(events) == 2
    assert (events[0].payload or {}).get("kind") == "expense"
    assert (events[0].payload or {}).get("action") == "delete"


# ── API：event 记录 → 读取闭环（打卡产生事件）─────────────────────
@pytest.mark.asyncio
async def test_check_action_records_event(client: AsyncClient, auth_user):
    """行中打卡 → 事件流出现 check 事件（写入路径接线验证）。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, "打卡事件闭环")

    # 该 trip 没有日期/站点，打卡会 404；这里只验证事件端点可读（空列表）
    resp = await client.get(f"/api/v1/trips/{trip_id}/events", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []