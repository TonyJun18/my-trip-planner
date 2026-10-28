"""AgentLoop 运行时单测（runtime.py）。

用 mock provider 阻断真实 LLM（开发环境配置了真实 provider，不 mock 会真调模型），
用假 AIMessage 模拟带/不带 tool_calls 的响应，覆盖：
- 无工具轮 → 直接返回输出
- 有工具轮 → 执行工具 → 回填 ToolMessage → 再回 LLM
- 工具失败 → is_error 回填，不打断循环
- validator 校验失败 → 反馈重试 → 成功完成
- validator 超限 → failed
- 达到 max_iterations → failed（护栏）
- terminate / should_stop_after_turn → 提前结束
- 输出被截断（stop_reason=length）→ 工具不执行、按 error 回填
- before_tool_call 拦截
- 事件序列（agent_start → ... → agent_end）完整
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.runtime import AgentEvent, AgentLoop, AgentTool


def _aimsg(
    content: str = "ok",
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    stop_reason: str | None = None,
) -> AIMessage:
    """构造一条假 AIMessage（模拟 provider 返回）。"""
    meta = {"stop_reason": stop_reason} if stop_reason else {}
    if tool_calls:
        # langchain structured tool_calls（OpenAI 格式）
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
            response_metadata=meta,
        )
    return AIMessage(content=content, response_metadata=meta)


class FakeChatModel:
    """伪 langchain ChatModel：bind_tools 返回自身，ainvoke 从 provider 取下一条 AIMessage。"""

    def __init__(self, prov: FakeProvider):
        self._prov = prov

    def bind_tools(self, tools: Any) -> FakeChatModel:
        return self

    async def ainvoke(self, messages: Any) -> AIMessage:
        return await self._prov()


class FakeProvider:
    """伪 provider：内部持有 FakeChatModel，走真实的 invoke_with_resilience 路径（含熔断/重试）。"""

    name = "fake"
    model_id = "fake-model"

    def __init__(self, responses: list[AIMessage]):
        self.responses = list(responses)
        self.calls = 0

    def get_chat_model(self, temperature: float = 0.2) -> FakeChatModel:
        return FakeChatModel(self)

    async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage:
        self.calls += 1
        if len(self.responses) < self.calls:
            raise AssertionError(f"FakeProvider 响应耗尽（第 {self.calls} 次调用）")
        return self.responses[self.calls - 1]


@pytest.fixture
def loop_factory():
    """返回 (responses, **kwargs) -> (loop, provider) 的工厂（注入伪 provider，不触网络）。"""
    def _build(responses: list[AIMessage], **loop_kwargs: Any) -> tuple[AgentLoop, FakeProvider]:
        loop = AgentLoop(system_prompt="test", provider="fake", **loop_kwargs)
        prov = FakeProvider(responses)
        loop._provider = prov  # type: ignore[attr-defined]  (注入伪 provider)
        return loop, prov

    return _build


# ═══════════════ 用例 ═══════════════

async def test_no_tool_round(loop_factory):
    """无工具轮：LLM 直接返回文本 → 输出即结果。"""
    loop, prov = loop_factory([_aimsg('{"destination":"杭州"}')])
    result = await loop.run("杭州")
    assert result["status"] == "completed"
    assert result["output"] == '{"destination":"杭州"}'
    assert prov.calls == 1


async def test_with_tool_round(loop_factory):
    """工具轮：LLM 先要调用工具 → 执行 → 回填 ToolMessage → 再回 LLM → 完成。"""
    calls: list[tuple[str, dict]] = []

    async def _search(city: str, query: str | None = None, limit: int = 8) -> str:
        calls.append((city, {"query": query, "limit": limit}))
        return '{"results": [{"name": "西湖", "type": "attraction"}]}'

    tool = AgentTool(
        name="search_attractions", description="搜索景点",
        parameters=None, execute=_search,
    )
    responses = [
        _aimsg(tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "必去"}}]),
        _aimsg('{"destination":"杭州","days":[]}'),
    ]
    loop, prov = loop_factory(responses, tools=[tool])
    result = await loop.run("杭州")
    assert result["status"] == "completed"
    assert len(calls) == 1
    assert calls[0] == ("杭州", {"query": "必去", "limit": 8})
    # 消息历史包含 ToolMessage
    assert any(isinstance(m, ToolMessage) for m in result["messages"])
    assert prov.calls == 2


async def test_tool_failure_then_continue(loop_factory):
    """工具执行失败 → is_error 回填 → loop 继续（不打断），最终完成。"""
    async def _boom(city: str) -> str:
        raise RuntimeError("external down")

    tool = AgentTool(name="query_weather", description="查询天气", execute=_boom)
    responses = [
        _aimsg(tool_calls=[{"name": "query_weather", "args": {"city": "杭州"}}]),
        _aimsg('{"weather":"sunny"}'),
    ]
    loop, prov = loop_factory(responses, tools=[tool])
    result = await loop.run("天气")
    assert result["status"] == "completed"
    # 最后一条 tool 消息是 error
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs and tool_msgs[-1].status == "error"
    assert prov.calls == 2


async def test_validator_retry_then_success(loop_factory):
    """validator 校验失败 → 反馈重试 → 成功。"""
    def _validator(out: Any) -> Any:
        if isinstance(out, dict) and out.get("destination"):
            return {"clean": out["destination"]}
        raise ValueError("缺少 destination")

    responses = [
        _aimsg('{"days":[]}'),   # 校验失败（无 destination）
        _aimsg('{"destination":"北京"}'),  # 成功
    ]
    loop, prov = loop_factory(responses, validator=_validator)
    result = await loop.run("北京")
    assert result["status"] == "completed"
    assert result["output"] == {"clean": "北京"}
    assert result["corrections"] == 1
    assert prov.calls == 2


async def test_validator_exhausted(loop_factory):
    """validator 连续失败超限 → failed。"""
    def _always_bad(_: Any) -> Any:
        raise ValueError("bad")

    responses = [_aimsg("x"), _aimsg("y"), _aimsg("z"), _aimsg("w")]
    loop, prov = loop_factory(responses, validator=_always_bad, max_corrections=2)
    result = await loop.run("x")
    assert result["status"] == "failed"
    assert prov.calls == 3  # 1 次初始 + 2 次反馈重试


async def test_max_iterations(loop_factory):
    """护栏：LLM 一直要求工具 → 达到 max_iterations → failed。"""
    async def _tool(city: str) -> str:
        return "{}"

    tool = AgentTool(name="t", description="t", execute=_tool)
    # 每次都要工具，永不完成
    responses = [_aimsg(tool_calls=[{"name": "t", "args": {"city": "x"}}])] * 10
    loop, prov = loop_factory(responses, tools=[tool], max_iterations=3)
    result = await loop.run("x")
    assert result["status"] == "failed"
    assert "最大迭代" in (result["error"] or "")
    assert prov.calls == 3


async def test_terminate(loop_factory):
    """工具 terminate=True → 该轮工具执行完即停（不再回 LLM）。"""
    async def _notify_done() -> str:
        return "done"

    tool = AgentTool(name="notify_done", description="完成", execute=_notify_done, terminate=True)
    responses = [
        _aimsg(tool_calls=[{"name": "notify_done", "args": {}}]),
        _aimsg("不该到这一步"),  # 不应被调用
    ]
    loop, prov = loop_factory(responses, tools=[tool])
    result = await loop.run("x")
    assert result["status"] in ("completed", "stopped")
    assert prov.calls == 1  # 只有第一次


async def test_should_stop_after_turn(loop_factory):
    """should_stop_after_turn 钩子：turn 后提前结束。"""
    async def _stop(messages: Any, iterations: int) -> bool:
        return iterations >= 1

    loop, prov = loop_factory([_aimsg("v1"), _aimsg("v2")], should_stop_after_turn=_stop)
    result = await loop.run("x")
    assert result["status"] == "completed"
    assert prov.calls == 1


async def test_truncated_output_rejects_tools(loop_factory):
    """stop_reason=length → 工具不执行，统一按 error 回填，loop 失败。"""
    executed: list[str] = []

    async def _tool(city: str) -> str:
        executed.append(city)
        return "{}"

    tool = AgentTool(name="t", description="t", execute=_tool)
    responses = [
        _aimsg(tool_calls=[{"name": "t", "args": {"city": "x"}}], stop_reason="length"),
    ]
    loop, _ = loop_factory(responses, tools=[tool])
    result = await loop.run("x")
    assert result["status"] == "failed"
    assert executed == []  # 工具未被调用
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs and tool_msgs[-1].status == "error"


async def test_before_tool_call_block(loop_factory):
    """before_tool_call 拦截：返回 reason → 工具不执行，error 回填。"""
    executed: list[str] = []

    async def _tool(city: str) -> str:
        executed.append(city)
        return "{}"

    async def _block(tool: Any, args: dict) -> str:
        return "bash is disabled"

    tool = AgentTool(name="bash", description="bash", execute=_tool)
    responses = [
        _aimsg(tool_calls=[{"name": "bash", "args": {"city": "x"}}]),
        _aimsg("final"),
    ]
    loop, prov = loop_factory(responses, tools=[tool], before_tool_call=_block)
    await loop.run("x")
    assert executed == []
    assert prov.calls == 2  # 第一次工具被拦后继续回 LLM → final


async def test_event_sequence(loop_factory):
    """事件序列：agent_start → turn_start → message* → (tool) → turn_end → agent_end。"""
    events: list[str] = []
    seen: set[str] = set()

    async def _sink(ev: AgentEvent) -> None:
        events.append(ev.type)
        if ev.type not in seen:
            seen.add(ev.type)

    async def _tool() -> str:
        return "{}"

    tool = AgentTool(name="t", description="t", execute=_tool)
    responses = [
        _aimsg(tool_calls=[{"name": "t", "args": {}}]),
        _aimsg("done"),
    ]
    loop, _ = loop_factory(responses, tools=[tool], on_event=_sink)
    result = await loop.run("hi")
    assert result["status"] == "completed"
    assert events[0] == "agent_start"
    assert events[-1] == "agent_end"
    assert "message_start" in seen
    assert "message_update" in seen
    assert "tool_execution_start" in seen
    assert "tool_execution_end" in seen
    assert "turn_end" in seen


async def test_parallel_tool_calls_batch(loop_factory):
    """一次消息多个工具调用 → 全部执行并回填。"""
    executed: list[str] = []

    async def _a(city: str) -> str:
        executed.append("a")
        return '"a"'

    async def _b(city: str) -> str:
        executed.append("b")
        return '"b"'

    responses = [
        _aimsg(tool_calls=[
            {"name": "tool_a", "args": {"city": "x"}},
            {"name": "tool_b", "args": {"city": "x"}},
        ]),
        _aimsg('{"ok":true}'),
    ]
    loop, prov = loop_factory(responses, tools=[
        AgentTool(name="tool_a", description="a", execute=_a),
        AgentTool(name="tool_b", description="b", execute=_b),
    ])
    result = await loop.run("hi")
    assert result["status"] == "completed"
    assert sorted(executed) == ["a", "b"]
    assert prov.calls == 2


async def test_transform_context(loop_factory):
    """transform_context 钩子：在发 LLM 前可裁剪/压缩上下文。"""
    seen_ctx: list[int] = []

    async def _transform(messages: list) -> list:
        seen_ctx.append(len(messages))
        return messages[:1]  # 只保留 system（模拟压缩）

    loop, _ = loop_factory([_aimsg("ok")], transform_context=_transform)
    await loop.run("hi")
    assert seen_ctx == [1]  # 第一次调用只有 user message（system 由 loop 单独拼）


# ═══════════════ 可观测性：工具失败透传真实错误 ═══════════════

async def test_tool_failure_event_carries_real_error(loop_factory):
    """工具失败 → tool_execution_end 事件 metadata.error 带上真实异常，而非空。"""
    async def _boom(city: str) -> str:
        raise RuntimeError("amap 429 rate limited")

    tool = AgentTool(name="query_weather", description="天气", execute=_boom)
    events: list[AgentEvent] = []

    async def _sink(ev: AgentEvent) -> None:
        events.append(ev)

    responses = [
        _aimsg(tool_calls=[{"name": "query_weather", "args": {"city": "杭州"}}]),
        _aimsg("稍后重试"),
    ]
    loop, _ = loop_factory(responses, tools=[tool], on_event=_sink)
    await loop.run("天气")
    end_events = [e for e in events if e.type == "tool_execution_end"]
    assert end_events
    # 真实错误进事件 metadata（当前实现丢掉了 → 此断言先红）
    assert end_events[0].metadata.get("error") == "amap 429 rate limited"
    # ToolMessage 内容也带真实错误（替代空串）
    tool_msgs = [m for m in loop.messages if isinstance(m, ToolMessage)]
    assert tool_msgs and tool_msgs[-1].status == "error"
    assert "amap 429 rate limited" in tool_msgs[-1].content


async def test_tool_failure_is_retried_once_within_turn(loop_factory):
    """工具失败 → 同一轮内自动重试 1 次；重试成功则结果正常、事件不再标 error。"""
    attempts: list[int] = []

    async def _flaky(city: str) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("transient network error")
        return '{"weather":"sunny"}'

    tool = AgentTool(name="query_weather", description="天气", execute=_flaky)
    events: list[AgentEvent] = []
    async def _sink(ev: AgentEvent) -> None:
        events.append(ev)

    responses = [
        _aimsg(tool_calls=[{"name": "query_weather", "args": {"city": "杭州"}}]),
        _aimsg('{"done":true}'),
    ]
    loop, _ = loop_factory(responses, tools=[tool], on_event=_sink)
    result = await loop.run("天气")
    assert result["status"] == "completed"
    assert len(attempts) == 2  # 1 次失败 + 1 次重试成功
    end_events = [e for e in events if e.type == "tool_execution_end"]
    assert end_events
    # 重试成功 → 该事件不是 error
    assert end_events[0].tool_is_error is False
    assert end_events[0].metadata.get("error") is None