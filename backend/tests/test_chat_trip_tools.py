"""对话助手行程感知工具测试（方案 1：只读打通）。

覆盖：
- 工具存在性与装配：_chat_tools 包含 get_my_trips / get_trip_overview
- get_my_trips：owner 隔离（只看到自己的行程）；无行程返回空列表
- get_trip_overview：绑定行程缺省读取；快照优先；快照缺失回退 ORM；
  stops 来自 days（hotel=已安排住宿，不是候选池）；owner 隔离
- 截断：站点/天数超出预算 → truncated 标记
- 会话绑定：create_session 校验 context.trip_id owner（403）
- 系统提示词包含行程规则

mock 策略：需求读真实 DB（db_session fixture），不触 LLM；
AgentLoop 路径测试用 mock_llm（对齐 test_chat_service）。
"""
from __future__ import annotations

import inspect
import json
from datetime import date, timedelta
from typing import Any

import pytest

from app.agent.runtime import AgentTool
from app.agent.trip_tools import make_trip_tools
from app.core.exceptions import PermissionDeniedError
from app.models import Stop, Trip, TripDay, TripPlan
from app.services import chat_service, trip_service


async def _call_await(tool: AgentTool, **kwargs: Any) -> str:
    """执行 AgentTool（契约允许 sync 或 async，统一 await 结果）。"""
    raw = tool.execute(**kwargs)
    if inspect.isawaitable(raw):
        return await raw
    return raw


# ── 数据工厂 ─────────────────────────────────────────────────
async def _make_trip(db, owner: str, *, destination: str = "杭州", title: str | None = None) -> Trip:
    """建一个带 2 天行程的 Trip（ORM 直插，绕过 API）。"""
    trip = Trip(
        owner=owner,
        title=title or f"{destination}行程",
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
    await db.flush()
    return trip


async def _make_plan(db, trip: Trip, *, budget: dict | None = None) -> TripPlan:
    """为 trip 建 AI 规划快照（plan_data 含 days/budget）。"""
    plan = TripPlan(
        trip_id=trip.id,
        plan_data={
            "destination": trip.destination,
            "days": [
                {"day_number": 1, "date": trip.start_date.isoformat(), "theme": "西湖环湖",
                 "stops": [{"name": "灵隐寺", "type": "attraction"}]},
                {"day_number": 2, "date": (trip.start_date + timedelta(days=1)).isoformat(), "theme": "灵隐祈福",
                 "stops": [{"name": "龙井村", "type": "attraction"}]},
            ],
            "budget": budget or {"total_estimated": 1275.0,
                                 "by_type": {"attraction": 75.0, "hotel": 1200.0},
                                 "currency": "CNY"},
        },
        status="completed",
    )
    db.add(plan)
    await db.flush()
    return plan


# ── 工具存在性与装配 ────────────────────────────────────────
async def test_chat_tools_include_trip_tools(db_session):
    user = "user-tools"
    trip = await _make_trip(db_session, user)
    tools = chat_service._chat_tools(db=db_session, user_id=user, trip_id=trip.id)
    names = {t.name for t in tools}
    assert {"get_my_trips", "get_trip_overview"} <= names


async def test_trip_tools_retryable_readonly(db_session):
    """行程工具是只读：retryable=True（失败可安全重试，无副作用）。"""
    user = "user-ro"
    tools = make_trip_tools(db=db_session, owner=user)
    for t in tools:
        assert t.retryable is True


async def test_trip_tools_have_schema(db_session):
    """get_trip_overview 有参数 schema；get_my_trips 无参数。"""
    user = "user-schema"
    tools = {t.name: t for t in make_trip_tools(db=db_session, owner=user)}
    assert tools["get_my_trips"].parameters is None
    schema = tools["get_trip_overview"].parameters
    assert schema is not None
    assert "trip_id" in schema.model_fields


# ── get_my_trips ─────────────────────────────────────────────
async def test_get_my_trips_lists_own_only(db_session):
    user_a, user_b = "user-a", "user-b"
    await _make_trip(db_session, user_a, title="A 的杭州")
    await _make_trip(db_session, user_b, title="B 的北京", destination="北京")

    tools = {t.name: t for t in make_trip_tools(db=db_session, owner=user_a)}
    out = json.loads(await _call_await(tools["get_my_trips"]))
    assert out["count"] == 1
    assert out["items"][0]["title"] == "A 的杭州"


async def test_get_my_trips_empty(db_session):
    tools = {t.name: t for t in make_trip_tools(db=db_session, owner="nobody")}
    out = json.loads(await _call_await(tools["get_my_trips"]))
    assert out["count"] == 0
    assert out["items"] == []


# ── get_trip_overview ────────────────────────────────────────
async def test_overview_has_stops_not_candidates(db_session):
    """关键语义：overview 的 stops 来自 days（已安排站点），
    酒店是已安排住宿（type=hotel 的 stop），不是 hotels 候选池。"""
    user = "user-overview"
    trip = await _make_trip(db_session, user)
    await _make_plan(db_session, trip)

    tools = {t.name: t for t in make_trip_tools(db=db_session, owner=user, trip_id=trip.id)}
    out = json.loads(await _call_await(tools["get_trip_overview"]))
    assert out["trip_id"] == trip.id
    assert out["destination"] == "杭州"
    assert len(out["days"]) == 2
    day1_hotels = [s for s in out["days"][0]["stops"] if s["type"] == "hotel"]
    assert day1_hotels and day1_hotels[0]["name"] == "杭州西湖国宾馆"
    assert out["has_plan_snapshot"] is True
    assert out["budget"]["total_estimated"] == 1275.0
    assert out["budget"]["by_type"]["hotel"] == 1200.0


async def test_overview_binds_session_trip(db_session):
    """不传 trip_id → 使用会话绑定的行程。"""
    user = "user-bind"
    trip = await _make_trip(db_session, user)
    tools = {t.name: t for t in make_trip_tools(db=db_session, owner=user, trip_id=trip.id)}
    out = json.loads(await _call_await(tools["get_trip_overview"]))
    assert out["trip_id"] == trip.id


async def test_overview_owner_isolation(db_session):
    """B 用 A 的 trip_id 查 → 结构化错误，不透数据。"""
    user_a, user_b = "user-oa", "user-ob"
    trip = await _make_trip(db_session, user_a)
    tools = {t.name: t for t in make_trip_tools(db=db_session, owner=user_b)}
    out = json.loads(await _call_await(tools["get_trip_overview"], trip_id=trip.id))
    assert out["error"] == "trip_not_found"


async def test_overview_missing_trip_id(db_session):
    """未绑定且未传 trip_id → missing_trip_id 错误。"""
    tools = {t.name: t for t in make_trip_tools(db=db_session, owner="user-x")}
    out = json.loads(await _call_await(tools["get_trip_overview"]))
    assert out["error"] == "missing_trip_id"


async def test_overview_fallback_without_snapshot(db_session):
    """无 AI 快照 → 回退 ORM days，has_plan_snapshot=false。"""
    user = "user-fallback"
    trip = await _make_trip(db_session, user)  # 不建 plan
    tools = {t.name: t for t in make_trip_tools(db=db_session, owner=user, trip_id=trip.id)}
    out = json.loads(await _call_await(tools["get_trip_overview"]))
    assert out["has_plan_snapshot"] is False
    assert len(out["days"]) == 2
    assert out["stop_count"] == 3


async def test_overview_truncates_many_stops(db_session):
    """站点超过摘要阈值 → truncated=true（显式标记，不静默丢弃）。"""
    user = "user-trunc"
    trip = Trip(owner=user, title="大行程", destination="西安",
                start_date=date.today(), end_date=date.today() + timedelta(days=1),
                travelers=1, status="draft")
    db_session.add(trip)
    await db_session.flush()
    day = TripDay(trip=trip, day_number=1, note="一日")
    db_session.add(day)
    await db_session.flush()
    stops = [Stop(day=day, order_index=i, name=f"点{i}", stop_type="attraction") for i in range(1, 20)]
    db_session.add_all(stops)
    await db_session.flush()

    tools = {t.name: t for t in make_trip_tools(db=db_session, owner=user, trip_id=trip.id)}
    out = json.loads(await _call_await(tools["get_trip_overview"]))
    day0 = out["days"][0]
    assert day0["truncated"] is True
    assert len(day0["stops"]) <= 12
    assert out["stop_count"] == 19


async def test_overview_truncates_many_days(db_session):
    """天数超过摘要阈值 → days_truncated=true + 折叠标记。"""
    user = "user-days"
    trip = Trip(owner=user, title="长行程", destination="成都",
                start_date=date.today(), end_date=date.today() + timedelta(days=10),
                travelers=1, status="draft")
    db_session.add(trip)
    await db_session.flush()
    days = [TripDay(trip=trip, day_number=i, note=f"第{i}天") for i in range(1, 10)]
    db_session.add_all(days)
    await db_session.flush()

    tools = {t.name: t for t in make_trip_tools(db=db_session, owner=user, trip_id=trip.id)}
    out = json.loads(await _call_await(tools["get_trip_overview"]))
    assert out["days_truncated"] is True
    assert len(out["days"]) == 8  # 7 天 + 折叠标记


# ── 会话绑定校验 ─────────────────────────────────────────────
async def test_create_session_rejects_foreign_trip(db_session):
    """绑定他人行程 → 403（PermissionDeniedError），不静默解绑。"""
    owner_a = "bind-a"
    owner_b = "bind-b"
    trip = await _make_trip(db_session, owner_a)
    with pytest.raises(PermissionDeniedError):
        await chat_service.create_session(db_session, owner_b, context={"trip_id": trip.id})


async def test_create_session_with_own_trip_ok(db_session):
    """绑定自己的行程 → 创建成功，context 保留 trip_id。"""
    user = "bind-own"
    trip = await _make_trip(db_session, user)
    session = await chat_service.create_session(db_session, user, context={"trip_id": trip.id})
    assert session.context_json == {"trip_id": trip.id}


async def test_create_session_without_trip_ok(db_session):
    """无 trip_id 的会话照常创建。"""
    session = await chat_service.create_session(db_session, "plain-user")
    assert session.context_json is None


# ── send_message 端到端（mock LLM）──────────────────────────
async def test_send_message_with_trip_tool_call(db_session, monkeypatch):
    """绑定行程的会话发消息 → LLM 调 get_trip_overview → 回复基于真实行程。"""
    from langchain_core.messages import AIMessage

    user = "chat-trip"
    trip = await _make_trip(db_session, user)
    await _make_plan(db_session, trip)
    session = await chat_service.create_session(db_session, user, context={"trip_id": trip.id})

    responses = [
        AIMessage(content="", tool_calls=[{
            "name": "get_trip_overview", "args": {}, "id": "call-trip", "type": "tool_call",
        }], response_metadata={}),
        AIMessage(content="你第 1 晚住在杭州西湖国宾馆（湖景房，约 1200 元/晚）",
                  response_metadata={}),
    ]

    async def _fake_invoke(*args: Any, **kwargs: Any):
        return responses.pop(0)

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _fake_invoke)

    result = await chat_service.send_message(db_session, session, "我杭州行程第 1 晚住哪？", broadcast=False)
    assert result["status"] == "completed"
    assert "杭州西湖国宾馆" in result["reply"]
    # tool 消息持久化
    msgs, _ = await chat_service.list_messages(db_session, session.id)
    tool_msgs = [m for m in msgs if m.role == "tool"]
    assert any(m.tool_call and m.tool_call.get("name") == "get_trip_overview" for m in tool_msgs)


async def test_send_message_reports_trip_not_found(db_session, monkeypatch):
    """LLM 传了不属于用户的 trip_id → 工具返回错误 → 助手如实告知。"""
    from langchain_core.messages import AIMessage

    user_a, user_b = "chat-a", "chat-b"
    trip = await _make_trip(db_session, user_a)
    session = await chat_service.create_session(db_session, user_b)

    responses = [
        AIMessage(content="", tool_calls=[{
            "name": "get_trip_overview", "args": {"trip_id": trip.id}, "id": "call-x", "type": "tool_call",
        }], response_metadata={}),
        AIMessage(content="我无法读取这个行程：它不存在或不属于你。", response_metadata={}),
    ]

    async def _fake_invoke(*args: Any, **kwargs: Any):
        return responses.pop(0)

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _fake_invoke)

    result = await chat_service.send_message(db_session, session, "看看 trip/xxx", broadcast=False)
    assert result["status"] == "completed"
    assert "不存在" in result["reply"] or "不属于" in result["reply"]


# ── 系统提示词包含行程规则 ──────────────────────────────────
def test_system_prompt_mentions_trip_tools():
    prompt = chat_service._SYSTEM_PROMPT
    assert "get_my_trips" in prompt
    assert "get_trip_overview" in prompt
    assert "行程数据优先" in prompt