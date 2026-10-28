"""对话助手行程上下文注入测试（方案 3：双向感知）。

覆盖：
- 事件摘要纯函数：类型白名单过滤、条数截断、超长折叠、时间戳格式
- build_trip_context：绑定行程 → 注入行程元信息 + 最近变更 + 画像；
  未绑定 → 空串；行程不存在/无权限 → 空串（不报错）
- 画像注入：有画像 → 含跨会话用户画像；无画像 → 不含
- transform_context 钩子：把注入块作为 SystemMessage 插到最前；
  注入失败 → 原样返回消息（零侵入）
- 事件风暴治理：>8 条只取 8 + 折叠提示；白名单外类型不注入
- send_message 端到端（mock LLM）：绑定行程会话发消息 → transform 注入
  行程上下文（验证 LLM 第一轮能看到快照）

数据策略（对齐 test_chat_edit_trip）：
- 造数后 commit（独立 session 读已提交数据）
- 用 db_session.session_factory（conftest 已挂）开独立读 session
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select

from app.models import Stop, Trip, TripDay, TripEvent, UserProfile
from app.services import chat_service
from app.services.chat_trip_context import (
    _CONTEXT_EVENT_TYPES,
    _MAX_EVENTS,
    build_trip_context,
    make_transform_context,
    summarize_events,
)


# ── 数据工厂 ────────────────────────────────────────────────
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
    db.add(day1)
    await db.flush()
    db.add(Stop(day=day1, order_index=1, name="灵隐寺", stop_type="attraction",
                lat=30.24, lng=120.10, estimated_cost=75.0, estimated_duration_minutes=180))
    await db.commit()
    return trip


async def _make_events(db, trip_id: str, *, count: int = 3, types: list[str] | None = None) -> list[TripEvent]:
    """造事件（时间递增）。"""
    types = types or ["revise", "chat_edit", "revise"]
    evs = []
    for i in range(count):
        t = types[i % len(types)]
        ev = TripEvent(
            trip_id=trip_id,
            event_type=t,
            payload={"summary": f"变更 {i}：调整第 {i+1} 天" if i else "首次调整行程"},
            created_at=datetime.now(timezone.utc) - timedelta(minutes=count - i),
        )
        db.add(ev)
        evs.append(ev)
    await db.commit()
    return evs


async def _make_profile(db, owner: str) -> UserProfile:
    from app.models import User

    # user_profiles.user_id 有外键 → 先建 User（email 唯一，用 owner 派生）
    u = User(id=owner, email=f"{owner}@test.com", display_name=owner)
    db.add(u)
    await db.flush()
    p = UserProfile(
        user_id=owner,
        traveler_type="亲子出游",
        pace="relaxed",
        budget_tier="middle",
        favorite_cities=["杭州", "成都"],
        preferences_json={"avoid": ["夜店"]},
    )
    db.add(p)
    await db.commit()
    return p


async def _fresh_db(db):
    """从 session_factory 开独立读 session（读已提交数据）。"""
    factory = getattr(db, "session_factory", None)
    if factory is None:
        return db
    return await factory().__aenter__()


# ── 事件摘要纯函数 ──────────────────────────────────────────
def test_summarize_events_basic():
    ev1 = TripEvent(trip_id="t", event_type="revise", payload={"summary": "调整第 2 天"},
                    created_at=datetime.now(timezone.utc))
    ev2 = TripEvent(trip_id="t", event_type="chat_edit", payload={"summary": "对话改名"},
                    created_at=datetime.now(timezone.utc))
    lines = summarize_events([ev1, ev2])
    assert len(lines) == 2
    assert "[revise]" in lines[0]
    assert "调整第 2 天" in lines[0]
    assert "[chat_edit]" in lines[1]


def test_summarize_events_truncates_long():
    ev = TripEvent(trip_id="t", event_type="revise",
                   payload={"summary": "x" * 200},
                   created_at=datetime.now(timezone.utc))
    lines = summarize_events([ev])
    assert "…" in lines[0]
    assert len(lines[0]) < 200


def test_summarize_events_respects_limit():
    evs = [
        TripEvent(trip_id="t", event_type="revise", payload={"summary": f"e{i}"},
                  created_at=datetime.now(timezone.utc))
        for i in range(15)
    ]
    lines = summarize_events(evs)
    assert len(lines) == _MAX_EVENTS  # 8


# ── build_trip_context ─────────────────────────────────────
async def test_context_without_trip_is_empty(db_session):
    ctx = await build_trip_context(db_session, user_id="u1", trip_id=None)
    assert ctx == ""


async def test_context_unbound_owner_is_empty(db_session):
    """行程存在但不属于该用户 → 空串（不报错、不泄露）。"""
    trip = await _make_trip(db_session, "owner-a")
    ctx = await build_trip_context(db_session, user_id="owner-b", trip_id=trip.id)
    assert ctx == ""


async def test_context_injects_trip_meta_and_events(db_session):
    user = "ctx-user"
    trip = await _make_trip(db_session, user)
    await _make_events(db_session, trip.id, count=3)

    ctx = await build_trip_context(db_session, user_id=user, trip_id=trip.id)
    assert "杭州行程" in ctx
    assert "最近行程变更" in ctx
    assert "[revise]" in ctx
    assert "首次调整行程" in ctx


async def test_context_omits_non_whitelist_events(db_session):
    """白名单外类型（check/comment/vote）不注入。"""
    user = "ctx-filter"
    trip = await _make_trip(db_session, user)
    await _make_events(db_session, trip.id, count=1, types=["comment"])  # 只在 comment
    await _make_events(db_session, trip.id, count=1, types=["vote"])

    ctx = await build_trip_context(db_session, user_id=user, trip_id=trip.id)
    # 无白名单事件 → 只有行程元信息，无「最近行程变更」段
    assert "最近行程变更" not in ctx


async def test_context_event_storm_folds(db_session):
    """>8 条白名单事件 → 注入 8 条 + 折叠提示。"""
    user = "ctx-storm"
    trip = await _make_trip(db_session, user)
    await _make_events(db_session, trip.id, count=12, types=["revise"])

    ctx = await build_trip_context(db_session, user_id=user, trip_id=trip.id)
    assert "另有" in ctx  # 折叠提示
    # 事件行数 = 8 + 折叠 = 9
    assert ctx.count("[revise]") == 8


async def test_context_injects_profile(db_session):
    user = "ctx-prof"
    trip = await _make_trip(db_session, user)
    await _make_profile(db_session, user)

    ctx = await build_trip_context(db_session, user_id=user, trip_id=trip.id)
    assert "跨会话用户画像" in ctx
    assert "亲子出游" in ctx


async def test_context_no_profile_omits_profile_section(db_session):
    user = "ctx-noprof"
    trip = await _make_trip(db_session, user)
    ctx = await build_trip_context(db_session, user_id=user, trip_id=trip.id)
    assert "跨会话用户画像" not in ctx


# ── transform_context 钩子 ─────────────────────────────────
async def test_transform_injects_system_message_first(db_session):
    from langchain_core.messages import AIMessage, HumanMessage

    user = "tf-user"
    trip = await _make_trip(db_session, user)
    make = make_transform_context(db_session, user_id=user, trip_id=trip.id)
    messages = [HumanMessage(content="你好")]
    out = await make(messages)
    assert len(out) == 2
    assert out[0].type == "system"
    assert "当前行程上下文" in out[0].content
    assert out[1] is messages[0]


async def test_transform_unbound_returns_unchanged(db_session):
    make = make_transform_context(db_session, user_id="u", trip_id=None)
    messages = [{"type": "human", "content": "hi"}]
    out = await make(messages)
    assert out is messages  # 原样


# ── send_message 端到端（mock LLM）─────────────────────────
async def test_send_message_injects_trip_context(db_session, monkeypatch):
    """绑定行程会话发消息 → transform 注入行程上下文（LLM 第一轮可见快照）。"""
    from langchain_core.messages import AIMessage

    user = "e2e-ctx"
    trip = await _make_trip(db_session, user)
    await _make_events(db_session, trip.id, count=2, types=["revise"])
    session = await chat_service.create_session(db_session, user, context={"trip_id": trip.id})

    seen: list[list[Any]] = []

    async def _fake_invoke(*args, **kwargs):
        messages = args[1]
        seen.append(messages)
        # 第二轮无工具调用直接回复
        return AIMessage(content="好的，我知道了", response_metadata={})

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _fake_invoke)
    r = await chat_service.send_message(db_session, session, "你好", broadcast=False)
    assert r["status"] == "completed"

    # 第一轮 LLM 消息里应包含注入的行程系统消息
    assert seen
    first_round = seen[0]
    assert any(getattr(m, "type", None) == "system" and "当前行程上下文" in str(getattr(m, "content", ""))
               for m in first_round)


async def test_send_message_without_bind_no_inject(db_session, monkeypatch):
    """未绑定行程 → 不注入（零噪音）。"""
    from langchain_core.messages import AIMessage

    user = "e2e-nobind"
    session = await chat_service.create_session(db_session, user)

    seen: list[list[Any]] = []

    async def _fake_invoke(*args, **kwargs):
        messages = args[1]
        seen.append(messages)
        return AIMessage(content="你好", response_metadata={})

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _fake_invoke)
    r = await chat_service.send_message(db_session, session, "你好", broadcast=False)
    assert r["status"] == "completed"

    first_round = seen[0]
    assert not any(getattr(m, "type", None) == "system" and "当前行程上下文" in str(getattr(m, "content", ""))
                   for m in first_round)