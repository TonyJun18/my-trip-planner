"""对话式行程助手（B 期）API：REST 会话/消息 + WebSocket 流式。

REST：
- POST   /chat/sessions                      创建会话
- GET    /chat/sessions                      列出我的会话
- GET    /chat/sessions/{id}                 会话详情
- DELETE /chat/sessions/{id}                 删除会话（级联删消息）
- GET    /chat/sessions/{id}/messages        历史消息
- POST   /chat/sessions/{id}/messages        发送消息（AgentLoop 执行，返回最终回复）

WS：
- /ws/chat/{session_id}                      流式接收 assistant_delta / tool_start /
                                              tool_end / assistant_done（鉴权：Bearer JWT）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.ws import _send_safe, _user_from_ws
from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models import User
from app.schemas import (
    ChatMessageListOut,
    ChatMessageOut,
    ChatSendIn,
    ChatSessionCreate,
    ChatSessionListOut,
    ChatSessionOut,
)
from app.services import chat_service
from app.services.ws_broadcast import hub

router = APIRouter(prefix="/chat", tags=["chat"])


def _session_out(session) -> ChatSessionOut:
    """ChatSession ORM → Out（context 从 context_json 映射）。"""
    return ChatSessionOut(
        id=session.id,
        title=session.title,
        context=session.context_json,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _msg_out(msg) -> ChatMessageOut:
    return ChatMessageOut(
        id=msg.id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content,
        reasoning=msg.reasoning,
        tool_call=msg.tool_call,
        tool_result=msg.tool_result,
        error=msg.error,
        created_at=msg.created_at,
    )


def _msg_out_from_dict(data: dict[str, Any]) -> ChatMessageOut:
    """把 service 返回的最终消息 dict 转成 ChatMessageOut。"""
    return ChatMessageOut.model_validate(data)


# ── 会话 ─────────────────────────────────────────────────────
@router.post("/sessions", response_model=ChatSessionOut, status_code=status.HTTP_201_CREATED, summary="创建对话会话")
async def create_session(
    data: ChatSessionCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChatSessionOut:
    """创建新会话（属主 = 当前用户）。"""
    session = await chat_service.create_session(
        db, user.id, title=data.title, context=data.context
    )
    return _session_out(session)


@router.get("/sessions", response_model=ChatSessionListOut, summary="列出我的会话")
async def list_sessions(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
) -> ChatSessionListOut:
    sessions, total = await chat_service.list_sessions(db, user.id, limit=limit, offset=offset)
    return ChatSessionListOut(items=[_session_out(s) for s in sessions], total=total)


@router.get("/sessions/{session_id}", response_model=ChatSessionOut, summary="会话详情")
async def get_chat_session(
    session_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChatSessionOut:
    session = await chat_service.get_session(db, user.id, session_id)
    if session is None:
        raise NotFoundError("会话不存在", code="chat_session_not_found")
    return _session_out(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除会话")
async def delete_chat_session(
    session_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    ok = await chat_service.delete_session(db, user.id, session_id)
    if not ok:
        raise NotFoundError("会话不存在", code="chat_session_not_found")


# ── 消息 ─────────────────────────────────────────────────────
@router.get("/sessions/{session_id}/messages", response_model=ChatMessageListOut, summary="会话历史消息")
async def list_chat_messages(
    session_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = 200,
    offset: int = 0,
) -> ChatMessageListOut:
    session = await chat_service.get_session(db, user.id, session_id)
    if session is None:
        raise NotFoundError("会话不存在", code="chat_session_not_found")
    messages, total = await chat_service.list_messages(db, session_id, limit=limit, offset=offset)
    return ChatMessageListOut(items=[_msg_out(m) for m in messages], total=total)


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageOut, summary="发送消息并获取回复")
async def send_chat_message(
    session_id: str,
    data: ChatSendIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChatMessageOut:
    """发送用户消息 → AgentLoop 执行 → 返回最终 assistant 消息。

    注意：这是同步接口（LLM 多轮工具调用可能在数秒内返回）；实时增量走 WS
    ``/ws/chat/{session_id}``。REST 返回的只是最终 assistant 消息，前端
    一般用 WS 展示增量，REST 用于轮询兜底。
    """
    session = await chat_service.get_session(db, user.id, session_id)
    if session is None:
        raise NotFoundError("会话不存在", code="chat_session_not_found")

    result = await chat_service.send_message(
        db, session, data.message, provider=data.provider, broadcast=True
    )
    # send_message 已持久化最终 assistant 消息并返回其 out
    return _msg_out_from_dict(result["message"])


# ── WebSocket：实时流式 ───────────────────────────────────────
@router.websocket("/ws/chat/{session_id}")
async def ws_chat(websocket: WebSocket, session_id: str, db: AsyncSession = Depends(get_session)) -> None:
    """会话流式通道：订阅 chat:{session_id} 广播。

    鉴权：Bearer JWT（query token= 或 Authorization header，二选一）。
    连接后：先推快照（现有消息 + 上一个 assistant_done），随后订阅实时事件
    （assistant_delta / tool_start / tool_end / assistant_done）。
    """
    user = await _user_from_ws(websocket, db)
    if user is None:
        await websocket.close(code=4401)
        return

    session = await chat_service.get_session(db, user.id, session_id)
    if session is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()

    # 快照：现有消息（最近 200 条）
    messages, _ = await chat_service.list_messages(db, session_id, limit=200)
    history = [_msg_out(m).model_dump(mode="json") for m in messages]
    if not await _send_safe(websocket, {"type": "snapshot", "messages": history}):
        return

    key = f"{chat_service.CHAT_BROADCAST_PREFIX}{session_id}"
    queue = hub.subscribe(key)
    try:
        while True:
            event = await queue.get()
            if not await _send_safe(websocket, event):
                break
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(key, queue)