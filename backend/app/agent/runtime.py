"""通用 Agent 运行时（AgentLoop）：移植 earendil-works/pi 的 pi-agent-core 设计理念，Python 重写。

设计文档：``docs/agent-runtime-design.md``（2026-10-27 立项，方案 A+B 组合）。

解决的问题：现有 agents.py 里 8 个 agent 全是手写函数式（固定 prompt → 一次 LLM →
执行固定工具 → 解析返回），模式高度重复；planner 的"校验失败重试"、critic 的
"评审轮次"都是手搓。本模块提供统一抽象：

- ``AgentTool``：声明式工具（pydantic 参数模型 → JSON schema → bind_tools）
- ``AgentLoop``：turn/事件流/多轮工具编排/terminate 护栏/输出校验重试/上下文变换钩子
- 事件流：agent_start → turn_start → message_start/update/end → tool_execution_start/end
  → turn_end → (validator 失败 → 反馈重试) → agent_end
- LLM 调用统一走 ``invoke_with_resilience``（保留重试/熔断/兜底/结构化观测）
- 零新依赖：不引 langgraph 新东西，也不引任何 npm 包

护栏（防无限循环）：
- ``max_iterations``：全局迭代上限（含工具轮 + 校验重生成轮，默认 settings.AGENT_MAX_ITERATIONS）
- ``max_corrections``：validator 失败反馈重试上限（默认 3）
- ``should_stop_after_turn`` / tool ``terminate``：提前结束信号
- 输出 token 截断（stop_reason=length）→ 工具参数可能被截断 → 一律按 is_error 拒绝执行
"""
from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.providers import BaseLLMProvider, get_provider
from app.common.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════
#  类型与事件
# ═══════════════════════════════════════════════════════════

# Agent 消息（直接用 langchain-core 消息对象，避免重复造轮子）
#  agent 内部消息 = BaseMessage（HumanMessage / AIMessage / SystemMessage / ToolMessage）


@dataclass
class AgentEvent:
    """一条 Agent 循环事件（类型化，兼容 WS 增量推送）。

    type ∈ agent_start|turn_start|message_start|message_update|message_end|
          tool_execution_start|tool_execution_end|turn_end|agent_end
    """

    type: str
    # message 相关
    message: Any | None = None
    delta: str | None = None               # message_update 的增量文本
    reasoning: str | None = None           # 本条 LLM 响应的思考过程（如有）
    # tool 相关
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: str | None = None
    tool_is_error: bool = False
    # 终态
    status: str | None = None
    error: str | None = None
    messages: list[Any] | None = None      # agent_end 时完整消息列表
    metadata: dict[str, Any] = field(default_factory=dict)


# 事件回调：可同步或异步（统一 await）
AgentEventSink = Callable[[AgentEvent], Awaitable[None] | None]


@dataclass
class AgentTool:
    """声明式工具。

    - ``parameters``：pydantic BaseModel（或 None）；用于生成 JSON schema 传给 LLM，
      并在执行前做参数校验。None 表示无参数。
    - ``execute``：执行函数，返回 observation 文本（结构化 JSON 字符串）；
      失败 raise，loop 统一捕获并按 is_error 处理（不打断循环，把错误喂回 LLM）。
    - ``terminate``：执行成功后置 True → 该批次所有工具完成后停止（跳过 follow-up LLM）。
    - ``retryable``：失败后是否允许 AgentLoop 同轮自动重试（默认 True——当前工具集
      全是只读查询，重试安全；将来接入有副作用的工具（下单/发邮件）必须置 False，
      避免重复副作用）。
    """

    name: str
    description: str
    execute: Callable[..., Awaitable[str] | str]
    parameters: type[Any] | None = None
    terminate: bool = False
    retryable: bool = True

    def to_json_schema(self) -> dict[str, Any]:
        """把 pydantic 参数模型转成 OpenAI function calling JSON schema。"""
        if self.parameters is None:
            return {"type": "object", "properties": {}}
        # pydantic v2 直接给 JSON schema
        schema = self.parameters.model_json_schema()
        # 去掉 pydantic 特有的 title/description 顶层噪音（保留字段描述）
        return schema


def _default_convert_to_llm(messages: list[Any]) -> list[Any]:
    """Agent 消息 → LLM 消息：过滤掉非 LLM 角色（与 pi defaultConvertToLlm 同思路）。"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    allowed = (HumanMessage, AIMessage, SystemMessage, ToolMessage)
    return [m for m in messages if isinstance(m, allowed)]


async def _maybe_await(value: Any) -> Any:
    """await 一个可能是同步也可能是异步的返回值。"""
    if value is not None and inspect.isawaitable(value):
        return await value
    return value


async def _emit(sinks: list[AgentEventSink], event: AgentEvent) -> None:
    for sink in sinks:
        try:
            result = sink(event)
            if result is not None:
                await result
        except Exception:  # 事件消费方失败绝不阻断循环
            logger.debug("Agent 事件消费失败 type=%s", event.type, exc_info=True)


# ═══════════════════════════════════════════════════════════
#  AgentLoop
# ═══════════════════════════════════════════════════════════

class AgentLoop:
    """有状态 Agent 循环（pi-agent-core 的 Python 移植，对照 agent-loop.ts runLoop）。

    用法::

        loop = AgentLoop(
            system_prompt="你是行程规划专家",
            tools=[AgentTool(name="search_attractions", ...)],
            validator=validate_plan,          # 可选：输出强校验
            on_event=my_ws_pusher,            # 可选：事件订阅
        )
        result = await loop.run("帮我规划杭州 3 天")
        # → {"status", "output"(validator 通过后产物), "messages", "trace", "corrections"}
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        tools: list[AgentTool] | None = None,
        provider: str = "auto",
        temperature: float = 0.2,
        max_iterations: int | None = None,
        max_corrections: int = 3,
        validator: Callable[[Any], Any] | None = None,
        validation_feedback: Callable[[Exception], Any] | None = None,
        convert_to_llm: Callable[[list[Any]], list[Any]] | None = None,
        transform_context: Callable[[list[Any]], Awaitable[list[Any]]] | None = None,
        before_tool_call: Callable[[AgentTool, dict[str, Any]], Awaitable[bool | str]] | None = None,
        after_tool_call: Callable[[AgentTool, dict[str, Any], str, bool], Awaitable[bool] | None] | None = None,
        should_stop_after_turn: Callable[[list[Any], int], Awaitable[bool]] | None = None,
        on_event: AgentEventSink | list[AgentEventSink] | None = None,
    ) -> None:
        from langchain_core.messages import SystemMessage

        self.system_prompt = system_prompt
        self.tools = tools or []
        self.provider = provider
        self.temperature = temperature
        self.max_iterations = max_iterations if max_iterations is not None else settings.AGENT_MAX_ITERATIONS
        self.max_corrections = max_corrections
        self.validator = validator
        self.validation_feedback = validation_feedback
        self.convert_to_llm = convert_to_llm or _default_convert_to_llm
        self.transform_context = transform_context
        self.before_tool_call = before_tool_call
        self.after_tool_call = after_tool_call
        self.should_stop_after_turn = should_stop_after_turn
        self._sinks: list[AgentEventSink] = [on_event] if callable(on_event) else list(on_event or [])

        self._messages: list[Any] = []
        self._system_message = SystemMessage(content=system_prompt)
        self._provider: BaseLLMProvider | None = None
        self._tool_map: dict[str, AgentTool] = {t.name: t for t in self.tools}

    # ── 只读状态 ──────────────────────────────────────────
    @property
    def provider_instance(self) -> BaseLLMProvider:
        if self._provider is None:
            self._provider = get_provider(self.provider)
        return self._provider

    @property
    def messages(self) -> list[Any]:
        return self._messages

    # ── 事件 ──────────────────────────────────────────────
    async def _fire(self, event: AgentEvent) -> None:
        await _emit(self._sinks, event)

    def _tool_schema(self) -> list[dict[str, Any]]:
        """生成 bind_tools 用的工具 schema（统一 name/description/parameters）。"""
        out = []
        for t in self.tools:
            schema = t.to_json_schema()
            out.append({
                "name": t.name,
                "description": t.description,
                **({"parameters": schema} if schema.get("properties") or schema.get("type") == "object" else {}),
            })
        return out

    def _llm_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        """从 AIMessage 提取 tool_calls（兼容 OpenAI 格式，含 id/name/args）。"""
        return getattr(response, "tool_calls", None) or []

    @staticmethod
    def _extract_reasoning(response: Any) -> str | None:
        """从 AIMessage 提取模型推理/思考过程（reasoning_content / additional_kwargs.reasoning）。

        兼容多个推理模型约定：
        - DeepSeek reasoner：``additional_kwargs.reasoning_content``（字符串）
        - OpenAI（gpt-*）reasoning：``additional_kwargs.reasoning`` / 列表形式的
          ``reasoning_effort`` 或 ``response_metadata`` 顶层 ``reasoning`` 段
        - 其它字段（ ``reasoning_summary`` 等）未命中即 None——绝不让思考过程
          破坏主回复契约（探测失败静默降级）。
        """
        if response is None:
            return None
        ak: dict[str, Any] = getattr(response, "additional_kwargs", None) or {}
        candidates: list[Any] = [
            ak.get("reasoning_content"),
            ak.get("reasoning"),
            getattr(response, "reasoning_content", None),
            (getattr(response, "response_metadata", None) or {}).get("reasoning"),
        ]
        for c in candidates:
            if isinstance(c, str) and c.strip():
                return c.strip()
            if isinstance(c, list):  # OpenAI 分段 reasoning（[{"type":"reasoning_text","text":...}]）
                try:
                    parts = [
                        seg.get("text")
                        for seg in c
                        if isinstance(seg, dict) and seg.get("type") == "reasoning_text"
                    ]
                    text = "".join(p for p in parts if p)
                    if text.strip():
                        return text.strip()
                except Exception:  # noqa: BLE001 — 结构不识别，静默放弃
                    continue
        return None

    # ── 主入口 ────────────────────────────────────────────
    async def run(self, human_message: str | list[Any]) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage

        if isinstance(human_message, str):
            prompt: Any = HumanMessage(content=human_message)
        else:
            prompt = human_message

        trace: list[dict[str, Any]] = []
        iterations = 0
        corrections = 0
        reasoning_accum: str | None = None
        last_output: Any = None
        last_status = "running"
        last_error: str | None = None

        await self._fire(AgentEvent(type="agent_start"))
        try:
            await self._fire(AgentEvent(type="turn_start"))
            await self._fire(AgentEvent(type="message_start", message=prompt))
            self._messages.append(prompt)
            await self._fire(AgentEvent(type="message_end", message=prompt))

            while iterations < self.max_iterations:
                iterations += 1

                # ── 上下文变换钩子（压缩/裁剪）──
                ctx_messages = self._messages
                if self.transform_context:
                    ctx_messages = await self.transform_context(self._messages)

                # ── LLM 调用（统一走 invoke_with_resilience；动态取引用使测试 monkeypatch 生效）──
                import app.agent.providers as providers_mod

                llm_messages = self.convert_to_llm([self._system_message, *ctx_messages])
                response = await providers_mod.invoke_with_resilience(
                    self.provider_instance, llm_messages, temperature=self.temperature,
                    tools=self._tool_schema() or None,
                )

                await self._fire(AgentEvent(type="message_start", message=response))
                reasoning_text = self._extract_reasoning(response)
                if reasoning_text:
                    reasoning_accum = reasoning_text if reasoning_accum is None else f"{reasoning_accum}\n\n{reasoning_text}"
                    await self._fire(AgentEvent(type="reasoning_start", reasoning=reasoning_text))
                content = str(getattr(response, "content", ""))
                await self._fire(AgentEvent(type="message_update", message=response, delta=content,
                                            reasoning=reasoning_text))
                await self._fire(AgentEvent(type="message_end", message=response))
                self._messages.append(response)

                tool_calls = self._llm_tool_calls(response)
                if not tool_calls:
                    # ── 无工具：校验输出 ──
                    if self.validator is not None:
                        try:
                            last_output = self.validator(await self._extract_json(content))
                            last_status = "completed"
                            break
                        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
                            corrections += 1
                            last_error = str(exc)
                            logger.info("Agent 输出校验失败 (correction=%d): %s", corrections, exc)
                            if corrections > self.max_corrections:
                                last_status = "failed"
                                last_error = f"输出多次校验失败: {exc}"
                                break
                            feedback = self._build_validation_feedback(exc)
                            self._messages.append(feedback)
                            continue
                    else:
                        last_output = content
                        last_status = "completed"
                        break

                # ── 有工具调用：执行批次 ──
                # stop_reason=length → 截断的参数不可信，全部按 is_error 拒绝（pi 同款护栏）
                if getattr(response, "response_metadata", {}).get("stop_reason") == "length":
                    for tc in tool_calls:
                        await self._fire(AgentEvent(
                            type="tool_execution_start", tool_name=tc.get("name", "?"),
                            tool_call_id=tc.get("id"), tool_args=tc.get("args") or {},
                        ))
                        await self._fire(AgentEvent(
                            type="tool_execution_end", tool_name=tc.get("name", "?"),
                            tool_call_id=tc.get("id"), tool_result="",
                            tool_is_error=True,
                            metadata={"error": "output truncated; args may be incomplete"},
                        ))
                        self._messages.append(self._tool_result_message(
                            tc, "", is_error=True,
                            error="LLM 输出被截断，工具参数可能不完整，请重新发起调用",
                        ))
                    await self._fire(AgentEvent(type="turn_end", status="failed",
                                                error="output truncated before tool execution"))
                    last_status = "failed"
                    last_error = "LLM 输出被 token 上限截断，工具未执行"
                    break

                terminate_batch = False
                for tc in tool_calls:
                    tool = self._tool_map.get(tc.get("name") or "")
                    if tool is None:
                        await self._fire(AgentEvent(type="tool_execution_start", tool_name=tc.get("name") or "?",
                                                    tool_call_id=tc.get("id"), tool_args=tc.get("args") or {}))
                        await self._fire(AgentEvent(type="tool_execution_end", tool_name=tc.get("name") or "?",
                                                    tool_call_id=tc.get("id"), tool_result="", tool_is_error=True,
                                                    metadata={"error": "unknown tool"}))
                        self._messages.append(self._tool_result_message(tc, "", is_error=True,
                                                                        error=f"未知工具 {tc.get('name')}"))
                        continue

                    args = tc.get("args") or {}
                    # before_tool_call 钩子：可拦截
                    if self.before_tool_call:
                        block = await _maybe_await(self.before_tool_call(tool, args))
                        if block:
                            reason = block if isinstance(block, str) else "blocked by before_tool_call"
                            await self._fire(AgentEvent(type="tool_execution_start", tool_name=tool.name,
                                                        tool_call_id=tc.get("id"), tool_args=args))
                            await self._fire(AgentEvent(type="tool_execution_end", tool_name=tool.name,
                                                        tool_call_id=tc.get("id"), tool_result="", tool_is_error=True,
                                                        metadata={"error": reason}))
                            self._messages.append(self._tool_result_message(tc, "", is_error=True, error=reason))
                            continue

                    result, is_error, tool_error = await self._execute_tool_with_retry(tool, args, tc)
                    trace.append({"tool": tool.name, "args": args,
                                  "observation": (result or tool_error or "")[:500], "is_error": is_error})

                    if self.after_tool_call:
                        term = await _maybe_await(self.after_tool_call(tool, args, result, is_error))
                        if term:
                            terminate_batch = True

                    if not is_error and tool.terminate:
                        terminate_batch = True

                    await self._fire(AgentEvent(type="tool_execution_end", tool_name=tool.name,
                                                tool_call_id=tc.get("id"), tool_result=result,
                                                tool_is_error=is_error,
                                                metadata={"error": tool_error} if is_error else {}))
                    self._messages.append(self._tool_result_message(
                        tc, result, is_error=is_error,
                        error=tool_error or ("tool error" if is_error else ""),
                    ))

                await self._fire(AgentEvent(type="turn_end", status="running" if not terminate_batch else "done"))

                # should_stop_after_turn 钩子
                if self.should_stop_after_turn:
                    stop = await self.should_stop_after_turn(self._messages, iterations)
                    if stop:
                        last_status = "completed" if last_output is not None else "stopped"
                        break

                if terminate_batch:
                    last_status = "completed" if last_output is not None else "stopped"
                    break

            else:
                # while 正常耗尽（iterations >= max_iterations）
                last_status = last_status if last_status != "running" else "failed"
                last_error = last_error or f"达到最大迭代次数 {self.max_iterations}"

            await self._fire(AgentEvent(type="agent_end", status=last_status, error=last_error,
                                        messages=self._messages))
            return {
                "status": last_status,
                "output": last_output,
                "messages": self._messages,
                "trace": trace,
                "corrections": corrections,
                "error": last_error,
                "reasoning": reasoning_accum,
                "provider": getattr(self.provider_instance, "name", "?"),
                "model": getattr(self.provider_instance, "model_id", None),
            }
        except Exception as exc:  # noqa: BLE001 — 汇总为失败（保持系统始终产出某种东西）
            logger.warning("AgentLoop 失败: %s", exc)
            await self._fire(AgentEvent(type="agent_end", status="failed", error=str(exc), messages=self._messages))
            return {"status": "failed", "output": None, "messages": self._messages,
                    "trace": trace, "corrections": corrections, "error": str(exc),
                    "reasoning": reasoning_accum,
                    "provider": getattr(self.provider_instance, "name", "?") if self._provider is not None else self.provider,
                    "model": getattr(self.provider_instance, "model_id", None) if self._provider is not None else None}

    # ── 辅助 ──────────────────────────────────────────────
    async def _execute_tool_with_retry(
        self, tool: AgentTool, args: dict[str, Any], tool_call: dict[str, Any]
    ) -> tuple[str, bool, str]:
        """执行一个工具（带失败重试），返回 (result, is_error, error_text)。

        重试策略：
        - 仅对 ``retryable=True`` 的工具重试 1 次（幂等/只读工具安全；有副作用的工具
          必须显式 ``retryable=False``，否则重试可能重复副作用）。
        - 重试后仍失败 → 把**真实错误文本**透传给调用方（事件 metadata + ToolMessage
          content + trace），绝不静默吞成空白，保证「失败可追溯、LLM 能读到原因」。
        - pydantic 参数校验失败（用户/LLM 给错参数）不重试——重试同参数必再失败。
        """
        fire_start = self._fire(AgentEvent(type="tool_execution_start", tool_name=tool.name,
                                           tool_call_id=tool_call.get("id"), tool_args=args))
        # 事件消耗方失败绝不能阻断执行
        try:
            await fire_start
        except Exception:  # noqa: BLE001
            logger.debug("tool_execution_start 事件发送失败", exc_info=True)

        final_error: str | None = None

        async def _attempt() -> tuple[str, bool, Exception | None]:
            nonlocal args
            try:
                # pydantic 参数校验（若有）
                if tool.parameters is not None:
                    args = tool.parameters.model_validate(args).model_dump()
                raw = await _maybe_await(tool.execute(**args))
                result = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
                return result, False, None
            except Exception as exc:  # noqa: BLE001 — 工具失败也要回填 observation
                return "", True, exc

        is_error = False
        result = ""
        err: Exception | None = None
        # 首次尝试
        result, is_error, err = await _attempt()
        if is_error and tool.retryable:
            from pydantic import ValidationError

            # 参数校验失败不重试（LLM 给的参数不合 schema，同参数重试必再失败）；
            # 只有真实执行异常（网络/外部服务）才重试。
            if not isinstance(err, ValidationError):
                logger.warning("Agent 工具 %s 首次失败，重试 1 次: %s", tool.name, err)
                result, is_error, err = await _attempt()

        if is_error:
            final_error = str(err) if err is not None else "tool error"
            logger.warning("Agent 工具 %s 失败: %s", tool.name, final_error)
            return result, True, final_error
        return result, False, ""

    def _tool_result_message(self, tool_call: dict[str, Any], content: str, *, is_error: bool, error: str = "") -> Any:
        from langchain_core.messages import ToolMessage

        return ToolMessage(
            content=content if not is_error else error or content,
            tool_call_id=tool_call.get("id") or f"call-{tool_call.get('name', 'tool')}",
            name=tool_call.get("name", ""),
            status="error" if is_error else "success",
        )

    async def _extract_json(self, text: str) -> Any:
        """从 LLM 输出提取第一个 JSON 对象/数组（容忍代码块与杂质）。"""
        import re

        if not text:
            return None
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

    def _build_validation_feedback(self, exc: Exception) -> Any:
        """构造校验失败反馈（默认可被注入的 builder 覆盖，用于保留调用方 i18n 文案）。"""
        if self.validation_feedback is not None:
            return self.validation_feedback(exc)
        return self._validation_feedback(exc)

    def _validation_feedback(self, exc: Exception) -> Any:
        """把校验异常转成给 LLM 的简短纠错消息（SystemMessage）。"""
        from langchain_core.messages import SystemMessage

        errors = getattr(exc, "errors", list)()
        lines = []
        for e in errors[:6]:
            loc = ".".join(str(x) for x in e.get("loc", []))
            lines.append(f"- {loc}: {e.get('msg', 'invalid')}")
        msg = "你的输出校验失败，请修正后重新输出完整 JSON（不要解释）：\n" + "\n".join(lines)
        return SystemMessage(content=msg)