"""对话式行程助手（B 期）服务/API 测试。

- 会话 CRUD：创建/列表/详情/删除（owner 隔离）
- 消息：发消息走 AgentLoop（mock LLM），返回 assistant 回复；工具调用持久化
- 上下文：会话历史注入 loop
- 安全：跨用户隔离（A 用户看不到 B 的会话）

mock 策略：不真调 LLM —— monkeypatch app.agent.providers.invoke_with_resilience
返回预置 AIMessage（对齐 test_agent.py 的替身思路）。
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from app.models import ChatMessage, ChatSession
from app.services import chat_service


# ── 工具函数 ─────────────────────────────────────────────────
def _aimsg(content: str = "ok", *, tool_calls: list[dict[str, Any]] | None = None, reasoning: str | None = None) -> AIMessage:
    if tool_calls:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tc["name"],
                    "args": tc.get("args") or {},
                    "id": tc.get("id") or f"call-{tc['name']}",
                    "type": "tool_call",
                }
                for tc in tool_calls
            ],
            response_metadata={},
        )
    kw = {}
    if reasoning:
        kw["additional_kwargs"] = {"reasoning_content": reasoning}
    return AIMessage(content=content, response_metadata={}, **kw)


@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch):
    """把 invoke_with_resilience 换成顺序返回预置响应的伪实现。"""
    responses: list[AIMessage] = []

    def _set(responses_list: list[AIMessage]) -> None:
        responses.clear()
        responses.extend(responses_list)

    async def _fake(*args: Any, **kwargs: Any) -> AIMessage:
        if not responses:
            raise AssertionError("mock_llm 响应耗尽")
        return responses.pop(0)

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _fake)
    return {"set": _set}


# ── 会话 CRUD ────────────────────────────────────────────────
async def test_create_and_get_session(db_session):
    session = await chat_service.create_session(db_session, "user-1", title="杭州咨询")
    assert session.id
    assert session.user_id == "user-1"
    assert session.title == "杭州咨询"

    got = await chat_service.get_session(db_session, "user-1", session.id)
    assert got is not None
    assert got.id == session.id


async def test_list_sessions_owner_isolated(db_session):
    await chat_service.create_session(db_session, "user-1", title="A 的会话")
    await chat_service.create_session(db_session, "user-2", title="B 的会话")

    items, total = await chat_service.list_sessions(db_session, "user-1")
    assert total == 1
    assert all(s.user_id == "user-1" for s in items)
    assert items[0].title == "A 的会话"


async def test_delete_session(db_session):
    session = await chat_service.create_session(db_session, "user-1")
    ok = await chat_service.delete_session(db_session, "user-1", session.id)
    assert ok is True
    assert await chat_service.get_session(db_session, "user-1", session.id) is None

    # 跨用户删不了别人会话
    s2 = await chat_service.create_session(db_session, "user-2")
    assert await chat_service.delete_session(db_session, "user-1", s2.id) is False


# ── 消息 ─────────────────────────────────────────────────────
async def test_send_message_returns_assistant_reply(db_session, mock_llm):
    """发消息 → loop 返回 assistant 回复；消息持久化。"""
    mock_llm["set"]([_aimsg("你好！我是旅行助手，想了解什么？")])
    session = await chat_service.create_session(db_session, "user-1", title="测试")

    result = await chat_service.send_message(db_session, session, "推荐杭州景点", broadcast=False)
    assert result["status"] == "completed"
    assert "你好" in result["reply"]

    items, total = await chat_service.list_messages(db_session, session.id)
    assert total == 2  # user + assistant
    assert items[0].role == "user"
    assert items[0].content == "推荐杭州景点"
    assert items[1].role == "assistant"
    assert "你好" in items[1].content


async def test_send_message_reasoning_persisted(db_session, mock_llm):
    """LLM 带 reasoning → 最终 assistant 消息 reasonng 落库、透出 out。"""
    mock_llm["set"]([_aimsg("杭州 3 日安排如下。", reasoning="先拆解用户需求，再查景点")])
    session = await chat_service.create_session(db_session, "user-1", title="思考")

    result = await chat_service.send_message(db_session, session, "杭州怎么玩", broadcast=False)
    assert result["status"] == "completed"
    # 服务返回 message 带 reasoning
    assert result["message"]["reasoning"] == "先拆解用户需求，再查景点"

    items, _ = await chat_service.list_messages(db_session, session.id)
    assistant = [m for m in items if m.role == "assistant"][-1]
    assert assistant.reasoning == "先拆解用户需求，再查景点"


async def test_send_message_no_reasoning_none(db_session, mock_llm):
    """普通模型无 reasoning → 落库为空，out.reasoning=None（契约稳定）。"""
    mock_llm["set"]([_aimsg("普通回复")])
    session = await chat_service.create_session(db_session, "user-1", title="无思考")
    result = await chat_service.send_message(db_session, session, "hi", broadcast=False)
    assert result["message"]["reasoning"] is None
    items, _ = await chat_service.list_messages(db_session, session.id)
    assistant = [m for m in items if m.role == "assistant"][-1]
    assert assistant.reasoning is None


async def test_send_message_reasoning_ws_broadcasted(db_session, mock_llm, monkeypatch):
    """broadcast=True 时 reasoning_start 事件经 hub 广播。"""
    from app.services import ws_broadcast

    published: list[dict] = []
    async def _fake_publish(key: str, payload: dict) -> None:
        published.append(payload)
    monkeypatch.setattr(ws_broadcast.hub, "publish", _fake_publish)

    mock_llm["set"]([_aimsg("好的", reasoning="思考一下")])
    session = await chat_service.create_session(db_session, "user-1", title="广播")
    await chat_service.send_message(db_session, session, "在吗", broadcast=True)
    reasoning_msgs = [p for p in published if p.get("type") == "reasoning_start"]
    assert reasoning_msgs and reasoning_msgs[0]["reasoning"] == "思考一下"


async def test_send_message_with_tool_call(db_session, mock_llm):
    """对话中 LLM 调用工具 → 工具执行 → 回填 tool 消息 → 最终回复。"""
    # 第一轮要调 search_attractions，第二轮给最终回复
    mock_llm["set"]([
        _aimsg(tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "必去"}}]),
        _aimsg("杭州必去西湖、灵隐寺。"),
    ])
    session = await chat_service.create_session(db_session, "user-1", title="工具测试")

    # 需要 patch tool 集（避免真实调用外部数据源）：直接把 _chat_tools() 换成带 fake 的
    from app.agent.runtime import AgentTool

    async def _fake_search(city: str, query: str | None = None, limit: int = 8) -> str:
        return '{"results": [{"name": "西湖", "type": "attraction"}]}'

    fake_tool = AgentTool(
        name="search_attractions",
        description="搜索景点",
        execute=_fake_search,
        parameters=None,
    )
    original = chat_service._chat_tools
    chat_service._chat_tools = lambda **kwargs: [fake_tool]  # type: ignore[assignment]
    try:
        result = await chat_service.send_message(db_session, session, "杭州有什么好玩的", broadcast=False)
    finally:
        chat_service._chat_tools = original  # type: ignore[assignment]

    assert result["status"] == "completed"
    assert "西湖" in result["reply"]

    items, _ = await chat_service.list_messages(db_session, session.id)
    roles = [m.role for m in items]
    assert "tool" in roles  # 工具消息被持久化


async def test_send_message_history_injected(db_session, mock_llm):
    """多轮对话：历史消息作为上下文注入 loop（第二次只带最近消息）。"""
    mock_llm["set"]([
        _aimsg("第一轮回复"),
        _aimsg("第二轮回复"),
    ])
    session = await chat_service.create_session(db_session, "user-1", title="历史")
    await chat_service.send_message(db_session, session, "第一问", broadcast=False)

    # 第二轮
    result = await chat_service.send_message(db_session, session, "第二问", broadcast=False)
    assert result["status"] == "completed"
    assert result["reply"] == "第二轮回复"

    items, total = await chat_service.list_messages(db_session, session.id)
    assert total == 4  # user, assistant, user, assistant


async def test_send_message_llm_failure(db_session, mock_llm):
    """LLM 失败（invoke 抛异常）→ 返回降级回复，不抛，消息仍持久化。"""
    async def _boom(*args: Any, **kwargs: Any) -> AIMessage:
        raise RuntimeError("llm down")

    import app.agent.providers as providers_mod
    import app.agent.runtime as runtime_mod
    # patch runtime 动态取用的 providers.invoke_with_resilience 与 service 使用处
    original = providers_mod.invoke_with_resilience
    providers_mod.invoke_with_resilience = _boom  # type: ignore[assignment]
    try:
        session = await chat_service.create_session(db_session, "user-1", title="失败")
        result = await chat_service.send_message(db_session, session, "在吗", broadcast=False)
    finally:
        providers_mod.invoke_with_resilience = original  # type: ignore[assignment]

    assert result["status"] == "failed"
    assert "抱歉" in result["reply"] or "失败" in result["reply"]
    items, total = await chat_service.list_messages(db_session, session.id)
    assert total >= 1


async def test_tool_failure_error_persisted(db_session, mock_llm):
    """工具失败（重试仍失败）→ tool 消息 error 列带真实错误（可追溯，不再空白）。"""
    mock_llm["set"]([
        _aimsg(tool_calls=[{"name": "query_weather", "args": {"city": "杭州"}}]),
        _aimsg("天气工具暂时不可用。"),
    ])
    from app.agent.runtime import AgentTool

    async def _boom(city: str) -> str:
        raise RuntimeError("amap 429 rate limited")

    fake_tool = AgentTool(name="query_weather", description="天气", execute=_boom, parameters=None)
    original = chat_service._chat_tools
    chat_service._chat_tools = lambda **kwargs: [fake_tool]  # type: ignore[assignment]
    try:
        session = await chat_service.create_session(db_session, "user-1", title="工具错误")
        result = await chat_service.send_message(db_session, session, "杭州天气", broadcast=False)
    finally:
        chat_service._chat_tools = original  # type: ignore[assignment]

    assert result["status"] == "completed"  # LLM 拿到错误后给出降级回复
    items, _ = await chat_service.list_messages(db_session, session.id)
    tool_msgs = [m for m in items if m.role == "tool"]
    assert tool_msgs
    # 真实错误进 error 列（当前实现丢掉了 → 此断言先红）
    assert tool_msgs[-1].error is not None
    assert "amap 429" in tool_msgs[-1].error
    # tool_result 如实标记失败
    assert tool_msgs[-1].tool_result == {"is_error": True}
    # 落到 tool 消息 content 的错误也能被 LLM 读到（非空白）
    assert "amap 429" in (tool_msgs[-1].content or "")