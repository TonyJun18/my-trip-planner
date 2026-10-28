"""对话助手行程修改工具测试（方案 2：读写打通，两阶段 HITL）。

覆盖：
- 工具装配：_chat_tools 包含 edit_trip，且 retryable=False（写操作不重试）
- 参数模型：edit_trip 强校验（非法 op 被 pydantic 拒绝）
- 预览轮（confirm=false）：不落库；目标错误 → rejected；DrivingGate 拒绝；
  成功返回 preview + expected_updated_at
- 应用轮（confirm=true）：复用 revise 管线原子落库 + TripEvent 留痕；
  并发基线过期 → conflict；DrivingGate 应用轮拒绝 → 回滚
- 端到端（mock LLM）：预览 → 确认 → 应用 全链路，行程真实改变

数据策略（对齐仓库惯例）：
- 造数后 ``await db_session.commit()``——预览轮用独立 session（db.session_factory）
  装载，只有已提交数据它才读得到。测试库按 owner 隔离，唯一前缀防串。
- 预览轮「不落库」断言：应用轮前后读 owner 的行程 stops 对比。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest

from app.agent.runtime import AgentTool
from app.agent.trip_edit_tool import DiffAction, make_edit_tool
from app.models import Stop, Trip, TripDay
from app.services import chat_service, trip_service


# ── 数据工厂（自包含；对齐 test_chat_trip_tools 语义） ────────
async def _make_trip(db, owner: str, *, destination: str = "杭州") -> Trip:
    trip = Trip(
        owner=owner,
        title=f"{destination}行程",
        destination=destination,
        departure="上海",
        start_date=date.today() + timedelta(days=7),
        end_date=date.today() + timedelta(days=9),
        travelers=2,
        budget=3000.0,
        status="draft",
    )
    db.add(trip)
    await db.flush()
    day1 = TripDay(trip=trip, day_number=1, date=trip.start_date, note="西湖环湖")
    day2 = TripDay(trip=trip, day_number=2, date=trip.start_date + timedelta(days=1), note="灵隐祈福")
    db.add_all([day1, day2])
    await db.flush()
    stops1 = [
        Stop(day=day1, order_index=1, name="灵隐寺", stop_type="attraction",
             lat=30.24, lng=120.10, estimated_cost=75.0, estimated_duration_minutes=180,
             description="飞来峰造像"),
        Stop(day=day1, order_index=2, name="杭州西湖国宾馆", stop_type="hotel",
             lat=30.23, lng=120.13, estimated_cost=1200.0, estimated_duration_minutes=None,
             description="湖景房"),
    ]
    stops2 = [
        Stop(day=day2, order_index=1, name="龙井村", stop_type="attraction",
             lat=30.19, lng=120.09, estimated_cost=0.0, estimated_duration_minutes=120,
             description="茶文化体验"),
    ]
    db.add_all(stops1 + stops2)
    await db.commit()  # 预览轮独立 session 需要已提交数据
    return trip


async def _read_stops(db, trip_id: str) -> list[str]:
    """用纯 SQL join 读站点名——绝不触发 ORM 关系惰性加载。

    async SQLAlchemy 中任何 lazy load 都会 MissingGreenlet；join 查询
    无状态、无 identity map、无过期问题。
    """
    from sqlalchemy import select
    from app.models import Stop, TripDay

    rows = (await db.execute(
        select(Stop.name)
        .join(TripDay, Stop.day_id == TripDay.id)
        .where(TripDay.trip_id == trip_id)
        .order_by(TripDay.day_number, Stop.order_index)
    )).scalars().all()
    return list(rows)


async def _stop_names(db, trip_id: str) -> list[str]:
    """读行程站点名（用独立 session，避开主 session 的 expired identity map）。

    应用轮被 DrivingGate 拒绝时执行 rollback()，主 session 的 identity map
    全部过期——同一 session 再查会触发 async 惰性加载 MissingGreenlet。
    """
    factory = getattr(db, "session_factory", None)
    if factory is not None:
        async with factory() as fresh_db:
            return await _read_stops(fresh_db, trip_id)
    return await _read_stops(db, trip_id)


async def _call_await(tool: AgentTool, **kwargs: Any) -> str:
    raw = tool.execute(**kwargs)
    if hasattr(raw, "__await__"):
        return await raw
    return str(raw)


def _j(tool_result: str) -> dict[str, Any]:
    return json.loads(tool_result)


# ── 工具装配 ────────────────────────────────────────────────
async def test_chat_tools_include_edit_trip_retryable_false(db_session):
    user = "edit-tool-user"
    trip = await _make_trip(db_session, user)
    tools = chat_service._chat_tools(db=db_session, user_id=user, trip_id=trip.id)
    edit = next((t for t in tools if t.name == "edit_trip"), None)
    assert edit is not None
    assert edit.retryable is False


async def test_edit_tool_params_schema(db_session):
    tool = make_edit_tool(db=db_session, owner="schema-user")
    assert tool.parameters is not None
    fields = tool.parameters.model_fields
    assert {"trip_id", "confirm", "expected_updated_at", "summary", "actions"} <= set(fields)


def test_diff_action_rejects_bad_op():
    with pytest.raises(Exception):
        DiffAction(op="teleport", day_number=1)


# ── 预览轮（confirm=false） ──────────────────────────────────
async def test_preview_does_not_persist(db_session):
    user = "pv-user"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)

    before = await _stop_names(db_session, trip.id)
    out = _j(await _call_await(tool, confirm=False, actions=[
        {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
         "fields": {"name": "灵隐寺（新）"}},
    ]))
    assert out["status"] == "preview"
    assert out["applied"] is False
    assert out["expected_updated_at"]
    assert len(out["changed"]) == 1

    after = await _stop_names(db_session, trip.id)
    assert after == before  # 预览不落库


async def test_preview_rejects_bad_target(db_session):
    user = "pv-bad"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)
    out = _j(await _call_await(tool, confirm=False, actions=[
        {"op": "replace", "day_number": 1, "target": {"name": "不存在的站"},
         "fields": {"name": "改名"}},
    ]))
    assert out["status"] == "rejected"
    assert "revise" in out.get("error", "")


async def test_preview_rejects_bad_day(db_session):
    user = "pv-day"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)
    out = _j(await _call_await(tool, confirm=False, actions=[
        {"op": "replace", "day_number": 99, "target": {"name": "灵隐寺"},
         "fields": {"name": "x"}},
    ]))
    assert out["status"] == "rejected"


async def test_preview_rejects_driving_violation(db_session):
    """预览：加一个超远站点 → DrivingGate 拒绝，带 issues，不落库。"""
    user = "pv-drive"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)
    before = await _stop_names(db_session, trip.id)
    out = _j(await _call_await(tool, confirm=False, actions=[
        {"op": "add", "day_number": 1,
         "fields": {"name": "布达拉宫", "type": "attraction", "lat": 29.65, "lng": 91.11,
                    "estimated_cost": 200, "duration_minutes": 300}},
    ]))
    assert out["status"] == "rejected"
    assert "driving" in out or "hint" in out
    assert await _stop_names(db_session, trip.id) == before


# ── 应用轮（confirm=true） ──────────────────────────────────
async def test_apply_persists_and_events(db_session):
    user = "ap-user"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)

    out = _j(await _call_await(tool, confirm=True, actions=[
        {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
         "fields": {"name": "灵隐寺（新）"}},
    ]))
    assert out["status"] == "applied"
    assert out["applied"] is True
    assert out["new_updated_at"]
    assert "灵隐寺（新）" in await _stop_names(db_session, trip.id)

    # 事件留痕
    from sqlalchemy import select
    from app.models import TripEvent

    events = (await db_session.execute(
        select(TripEvent).where(TripEvent.trip_id == trip.id)
    )).scalars().all()
    assert any(e.event_type == "chat_edit" for e in events)


async def test_apply_conflict_on_stale_baseline(db_session):
    user = "ap-conflict"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)
    before = await _stop_names(db_session, trip.id)

    out = _j(await _call_await(tool, confirm=True,
                               expected_updated_at="2000-01-01T00:00:00+00:00",
                               actions=[
                                   {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
                                    "fields": {"name": "x"}},
                               ]))
    assert out["status"] == "conflict"
    assert out["error"] == "trip_updated"
    assert await _stop_names(db_session, trip.id) == before


async def test_apply_without_baseline_allowed(db_session):
    """无基线（第一次应用）也允许——基线用于并发防护，不强制。"""
    user = "ap-nobase"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)
    out = _j(await _call_await(tool, confirm=True, actions=[
        {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
         "fields": {"name": "灵隐寺（无基线）"}},
    ]))
    assert out["status"] == "applied"
    assert "灵隐寺（无基线）" in await _stop_names(db_session, trip.id)


async def test_apply_driving_rejected_rolls_back(db_session):
    user = "ap-drive"
    trip = await _make_trip(db_session, user)
    # rollback 会使主 session 的 ORM 对象过期，先拷贝 id（字符串值，避免回滚后访问）
    trip_id = str(trip.id)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip_id)
    before = await _stop_names(db_session, trip_id)

    out = _j(await _call_await(tool, confirm=True, actions=[
        {"op": "add", "day_number": 1,
         "fields": {"name": "布达拉宫", "type": "attraction", "lat": 29.65, "lng": 91.11,
                    "estimated_cost": 200, "duration_minutes": 300}},
    ]))
    assert out["status"] == "rejected"
    assert await _stop_names(db_session, trip_id) == before


async def test_apply_owner_isolation(db_session):
    """B 修改 A 的行程 → trip_not_found（owner 隔离）。"""
    user_a, user_b = "ap-oa", "ap-ob"
    trip = await _make_trip(db_session, user_a)
    tool = make_edit_tool(db=db_session, owner=user_b, trip_id=trip.id)
    out = _j(await _call_await(tool, confirm=True, actions=[
        {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
         "fields": {"name": "x"}},
    ]))
    assert out["status"] == "error"
    assert out["error"] == "trip_not_found"
    assert "灵隐寺" in await _stop_names(db_session, trip.id)  # 未变


async def test_missing_trip_id_error(db_session):
    tool = make_edit_tool(db=db_session, owner="mx-user")
    out = _j(await _call_await(tool, confirm=False, actions=[
        {"op": "replace", "day_number": 1, "target": {"name": "x"}, "fields": {"name": "y"}},
    ]))
    assert out["status"] == "error"
    assert out["error"] == "missing_trip_id"


async def test_empty_actions_error(db_session):
    user = "empty-user"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)
    out = _j(await _call_await(tool, confirm=False, actions=[]))
    assert out["status"] == "error"
    assert out["error"] == "empty_actions"


# ── 归一化：绕过 AgentLoop 直接传 DiffAction ────────────────
async def test_direct_single_diffaction(db_session):
    """直接传单个 DiffAction 对象（非 list）→ 归一化后执行。"""
    user = "norm-user"
    trip = await _make_trip(db_session, user)
    tool = make_edit_tool(db=db_session, owner=user, trip_id=trip.id)
    out = _j(await _call_await(tool, confirm=False, actions=DiffAction(
        op="replace", day_number=1, target={"name": "灵隐寺"}, fields={"name": "归一化"}
    )))
    assert out["status"] == "preview"
    assert out["changed"][0]["target_name"] == "灵隐寺"


# ── 端到端（mock LLM）：预览 → 确认 → 应用 ──────────────────
async def test_e2e_preview_then_confirm(db_session, monkeypatch):
    """绑定行程会话：请求改行程 → LLM 两轮工具调用（预览+应用）→ 行程真实改变。"""
    from langchain_core.messages import AIMessage

    user = "e2e-user-mock"
    trip = await _make_trip(db_session, user)
    session = await chat_service.create_session(db_session, user, context={"trip_id": trip.id})

    # 预览轮：LLM 产出 diff → 工具返回 preview；助手转述并询问确认
    responses = [
        AIMessage(content="", tool_calls=[{
            "name": "edit_trip",
            "args": {"confirm": False, "actions": [
                {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
                 "fields": {"name": "灵隐寺（对话改）"}},
            ]},
            "id": "call-pv", "type": "tool_call",
        }], response_metadata={}),
        AIMessage(content="好的，请确认：我要把第 1 天的『灵隐寺』改名为『灵隐寺（对话改）』，确认吗？",
                  response_metadata={}),
    ]
    async def _fake_pv(*args, **kwargs):
        return responses.pop(0)
    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _fake_pv)

    r1 = await chat_service.send_message(db_session, session, "把第1天的灵隐寺改名", broadcast=False)
    assert r1["status"] == "completed"
    assert "确认" in r1["reply"]

    # 应用轮：LLM 带 confirm=true → 工具应用 → 助手回复成功
    responses2 = [
        AIMessage(content="", tool_calls=[{
            "name": "edit_trip",
            "args": {"confirm": True, "expected_updated_at": None, "actions": [
                {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
                 "fields": {"name": "灵隐寺（对话改）"}},
            ]},
            "id": "call-ap", "type": "tool_call",
        }], response_metadata={}),
        AIMessage(content="已应用修改：第 1 天的『灵隐寺』已改名为『灵隐寺（对话改）』。", response_metadata={}),
    ]
    async def _fake_ap(*args, **kwargs):
        return responses2.pop(0)
    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _fake_ap)

    r2 = await chat_service.send_message(db_session, session, "确认", broadcast=False)
    assert r2["status"] == "completed"
    assert "已应用" in r2["reply"]
    assert "灵隐寺（对话改）" in await _stop_names(db_session, trip.id)