"""对话式行程助手服务（B 期）。

基于 A 期 AgentLoop（runtime.py）提供多轮工具调用；会话与消息持久化到 Postgres
（chat_sessions / chat_messages）。工具集复用现有采集工具（search_attractions /
search_hotels / search_foods / query_weather / search_transport / collect_discount_rules）。

设计：
- 会话属主 = 登录用户（user_id 索引）；所有查询带 owner 隔离。
- 消息顺序依赖 created_at（不设自增 id）。
- 每次发送：持久化 user 消息 → AgentLoop.run（带事件回调持久化 assistant/tool 消息
  + 实时广播）→ 持久化最终 assistant 消息 → 返回。
- 上下文预算：简单策略=保留最近 N 条消息 + 首条（防无限增长）；B 期不做摘要压缩
  （transform_context 钩子预留）。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import AgentEvent, AgentLoop, AgentTool
from app.core.logging import get_logger
from app.models import ChatMessage, ChatSession
from app.services.ws_broadcast import hub

logger = get_logger(__name__)

# 广播 key 前缀
CHAT_BROADCAST_PREFIX = "chat:"

# 上下文预算：对话保留最近 N 条消息（user+assistant+tool），防无限增长
MAX_CONTEXT_MESSAGES = 40


# ═══════════════════════════════════════════════════════════
#  工具集（复用 agents.py 的 LangChain 工具，包成 AgentTool）
# ═══════════════════════════════════════════════════════════
def _as_agent_tool(lc_tool: Any) -> AgentTool:
    """把 LangChain @tool 包成 AgentTool（复用现有工具实现与数据源降级）。"""
    async def _execute(**kwargs: Any) -> str:
        # 调用 LangChain 工具（返回 str 或可 JSON 序列化对象）
        result = await lc_tool.ainvoke(kwargs)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

    return AgentTool(
        name=lc_tool.name,
        description=lc_tool.description or "",
        execute=_execute,
        parameters=None,  # 参数 schema 由 langchain 工具自描述（bind_tools 忽略 AgentTool.parameters）
    )


def _chat_tools() -> list[AgentTool]:
    """对话助手可用工具：现有 6 个采集/查询工具（复用真实数据源 + 熔断降级）。"""
    from app.agent import agents

    names = [
        "search_attractions",
        "search_hotels",
        "search_foods",
        "query_weather",
        "search_transport",
        "collect_discount_rules",
    ]
    tools = []
    for name in names:
        lc_tool = agents.TOOL_MAP.get(name) or agents.DISCOUNT_TOOLS[0] if name == "collect_discount_rules" else agents.TOOL_MAP.get(name)
        if lc_tool is not None:
            tools.append(_as_agent_tool(lc_tool))
    return tools


_SYSTEM_PROMPT = """你是一个智能旅行助手。你可以使用工具查询真实的景点、酒店、餐厅、天气、交通与折扣信息，
然后基于工具返回的结构化数据回答用户问题。

规则：
1. 需要城市/目的地信息时先调用对应工具获取真实数据，不要凭记忆编造景点/酒店/价格。
2. 工具返回的数据是 JSON；回答时用自然语言总结关键信息（名称、位置、大概花费、亮点），
   不要原样倾倒 JSON。
3. 如果工具不可用（返回错误），明确告诉用户当前无法获取该信息，不要编造。
4. 涉及「推荐理由/行程建议」时，基于工具结果给出合理建议；不确定的标注「建议以实际为准」。
5. 回答语言与用户保持一致（中文/英文）。"""


# ═══════════════════════════════════════════════════════════
#  会话 CRUD
# ═══════════════════════════════════════════════════════════
async def create_session(db: AsyncSession, user_id: str, *, title: str | None = None, context: dict | None = None) -> ChatSession:
    """新建会话（属主 = user_id）。"""
    session = ChatSession(
        user_id=user_id,
        title=(title or "新对话"),
        context_json=context,
    )
    db.add(session)
    await db.flush()
    return session


async def list_sessions(db: AsyncSession, user_id: str, *, limit: int = 50, offset: int = 0) -> tuple[list[ChatSession], int]:
    """列出用户的会话（最新在前）。"""
    total = await db.scalar(select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id))
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(desc(ChatSession.updated_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), int(total or 0)


async def get_session(db: AsyncSession, user_id: str, session_id: str) -> ChatSession | None:
    """取用户自己的会话（owner 隔离）。"""
    return await db.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
    )


async def delete_session(db: AsyncSession, user_id: str, session_id: str) -> bool:
    """删除会话（级联删消息）。返回是否删到。"""
    session = await get_session(db, user_id, session_id)
    if session is None:
        return False
    await db.delete(session)
    await db.flush()
    return True


# ═══════════════════════════════════════════════════════════
#  消息
# ═══════════════════════════════════════════════════════════
async def list_messages(db: AsyncSession, session_id: str, *, limit: int = 200, offset: int = 0) -> tuple[list[ChatMessage], int]:
    """列出会话消息（按时间正序）。"""
    total = await db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id))
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), int(total or 0)


async def _add_message(db: AsyncSession, session_id: str, *, role: str, content: str = "", **extra: Any) -> ChatMessage:
    """新增一条消息（不 commit，由请求级 session 统一提交）。"""
    msg = ChatMessage(session_id=session_id, role=role, content=content, **extra)
    db.add(msg)
    await db.flush()
    return msg


def _messages_to_llm(messages: list[ChatMessage]) -> list[Any]:
    """把持久化消息转为 langchain 消息（供 AgentLoop 上下文）。"""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    out: list[Any] = []
    for m in messages:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
        elif m.role == "tool":
            out.append(
                ToolMessage(
                    content=m.content or "",
                    tool_call_id=(m.tool_call or {}).get("id") or "chat-tool",
                    name=(m.tool_call or {}).get("name") or "",
                    status="error" if m.error else "success",
                )
            )
    return out


async def _last_messages(db: AsyncSession, session_id: str, limit: int = MAX_CONTEXT_MESSAGES) -> list[ChatMessage]:
    """取最近 N 条消息（时间序）。"""
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    )
    rows = (await db.scalars(stmt)).all()
    return list(reversed(rows))


# ═══════════════════════════════════════════════════════════
#  对话执行（AgentLoop）
# ═══════════════════════════════════════════════════════════
async def send_message(
    db: AsyncSession,
    session: ChatSession,
    message: str,
    *,
    provider: str = "auto",
    broadcast: bool = True,
) -> dict[str, Any]:
    """发送用户消息 → AgentLoop 多轮工具调用 → 返回最终 assistant 回复。

    事件回调：assistant 增量/完整 / tool 调用 → 持久化 + 广播（chat:{session_id}）。
    返回 {"status", "reply", "messages"(本轮新增), "trace"}
    """
    session_id = session.id
    # 1) 持久化用户消息
    await _add_message(db, session_id, role="user", content=message)
    session.title = message[:50] if not session.title or session.title == "新对话" else session.title
    await db.flush()

    # 2) 组装 AgentLoop（系统提示 + 工具 + 上下文 = 历史消息 + 新用户消息）
    history = await _last_messages(db, session_id)
    loop = AgentLoop(
        system_prompt=_SYSTEM_PROMPT,
        tools=_chat_tools(),
        provider=provider,
        max_iterations=8,  # 对话型护栏：最多 8 轮工具/重生成
        max_corrections=2,
        on_event=_chat_event_sink(db, session_id, broadcast),
    )

    # 3) 历史消息作为上下文（新用户消息由 loop.run 追加）
    #    注意：历史里最后一条是刚存的用户消息；loop.run 会再 append 一条相同的 → 去重
    history_llm = _messages_to_llm(history[:-1])  # 去掉刚入的 user（loop 会加）
    # 让 loop 的历史上下文只含 system 之前的消息；system prompt 由 loop 注入
    loop._messages = history_llm  # type: ignore[attr-defined]  (注入历史上下文)

    # 4) 执行
    result = await loop.run(message)
    reply = ""
    if result["status"] == "completed":
        # 输出是纯文本（无 validator → output 即 LLM 文本）
        reply = result["output"] if isinstance(result["output"], str) else json.dumps(result["output"], ensure_ascii=False)
    else:
        # 降级：失败时给出友好文案（不把原始 error 直接给用户；原始错误记日志）
        logger.warning("ChatAgent 失败 session=%s err=%s", session_id, result.get("error"))
        reply = "抱歉，我暂时无法回答（服务正忙，请稍后再试）。"

    # 5) 持久化最终 assistant 消息（事件回调里已存部分；这里只存最终一条避免重复）
    final_msg = await _add_message(db, session_id, role="assistant", content=reply,
                                   error=result.get("error") if result["status"] != "completed" else None)
    await db.flush()

    # 广播最终回复
    if broadcast:
        await hub.publish(f"{CHAT_BROADCAST_PREFIX}{session_id}", {
            "type": "assistant_done",
            "message": _msg_out(final_msg),
        })

    return {
        "status": result["status"],
        "reply": reply,
        "message": _msg_out(final_msg),
        "trace": result["trace"],
        "provider": result.get("provider"),
        "model": result.get("model"),
    }


def _chat_event_sink(db: AsyncSession, session_id: str, broadcast: bool):
    """构造 AgentLoop 事件回调：把 assistant/tool 增量持久化 + 广播。"""

    # assistant 增量在 message_update 时拿到的是完整文本（非流式 delta），这里简单持久化
    async def _sink(event: AgentEvent) -> None:
        # 只关注需要持久化/广播的事件
        if event.type == "message_start" and event.message is not None:
            # assistant 消息起始：不单独广播（等 message_end 汇总）
            return
        if event.type == "message_update":
            # 增量（当前实现为整段文本，非流式）；广播给前端做「正在思考」占位
            if broadcast:
                await hub.publish(f"{CHAT_BROADCAST_PREFIX}{session_id}", {
                    "type": "assistant_delta",
                    "delta": event.delta or "",
                })
            return
        if event.type == "tool_execution_start":
            if broadcast:
                await hub.publish(f"{CHAT_BROADCAST_PREFIX}{session_id}", {
                    "type": "tool_start",
                    "tool_name": event.tool_name,
                    "args": event.tool_args,
                })
            return
        if event.type == "tool_execution_end":
            # 真实错误透传（runtime 现在把错误放 metadata.error；不再空白）
            err_text = event.metadata.get("error") if isinstance(event.metadata, dict) else None
            content = event.tool_result or ""
            # 失败时把真实错误写进 content，让 LLM 能读到「为什么失败」，而非空白
            if event.tool_is_error and err_text:
                content = f"工具执行失败: {err_text}"
            # 持久化 tool 消息
            tc = {"id": event.tool_call_id, "name": event.tool_name}
            await _add_message(
                db, session_id, role="tool",
                content=content,
                tool_call=tc,
                tool_result={"is_error": event.tool_is_error},
                error=json.dumps({"error": err_text}, ensure_ascii=False) if event.tool_is_error and err_text else None,
            )
            await db.flush()
            if broadcast:
                await hub.publish(f"{CHAT_BROADCAST_PREFIX}{session_id}", {
                    "type": "tool_end",
                    "tool_name": event.tool_name,
                    "tool_call_id": event.tool_call_id,
                    "is_error": event.tool_is_error,
                })
            return

    return _sink


def _msg_out(msg: ChatMessage) -> dict[str, Any]:
    return {
        "id": msg.id,
        "session_id": msg.session_id,
        "role": msg.role,
        "content": msg.content,
        "tool_call": msg.tool_call,
        "tool_result": msg.tool_result,
        "error": msg.error,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }