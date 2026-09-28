"""WebSocket 端点：规划任务 T-A-O 流式推送 + 协作实时同步。

两个通道（均基于 ``ws_broadcast`` 进程内 pub/sub）：

1. ``/ws/planner/tasks/{task_id}``
   - 鉴权：Bearer JWT（query ``token=`` 或 ``Authorization`` header，二选一）
   - 连接后先推送当前快照（status + 已有 trace），随后 Agent 每产生一条
     trace 实时推送 ``{"type":"trace"}``；任务结束推送 ``{"type":"status"}``。
   - 断线重连：轮询 REST 兜底仍然可用（规划页轮询逻辑保留）。

2. ``/ws/trips/{trip_id}/collab``
   - 鉴权：分享令牌（``share_token``，query ``token=``；``edit=1`` 时用
     ``edit_token``）
   - 评论 / 投票 / 受邀编辑（勾选、改名备注、顺序重排）由 REST handler
     落库后向该行程频道广播，所有打开分享页的连接实时收到增量事件。
   - 事件：``comment / vote / stop / reorder``。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.models import User
from app.services import collab_service, planning_service
from app.services.ws_broadcast import hub

logger = get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["ws"])


# ── 鉴权辅助 ──────────────────────────────────────────────────
async def _user_from_ws(websocket: WebSocket, db: AsyncSession) -> User | None:
    """从 WS 握手解析用户：优先 Authorization header，其次 query token=。"""
    token: str | None = (
        websocket.query_params.get("token")
        or (websocket.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        or None
    )
    if not token:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    return await db.get(User, user_id)


async def _authorize_ws(websocket: WebSocket, db: AsyncSession, *, token: str | None = None) -> bool:
    """校验分享/编辑令牌有效性（失败返回 False，调用方负责 close）。"""
    if not token:
        return False
    try:
        trip = await collab_service._get_trip_by_token(db, token)
        return trip is not None
    except Exception:  # noqa: BLE001 — 令牌无效即拒绝
        return False


async def _send_safe(websocket: WebSocket, message: dict[str, Any]) -> bool:
    """尽力 send_json：连接已关闭时返回 False（调用方据此退出订阅循环）。"""
    try:
        await websocket.send_json(message)
        return True
    except Exception:  # noqa: BLE001 — RuntimeError: closed / 网络中断
        return False


# ── 规划任务：T-A-O 流式轨迹 ──────────────────────────────────
@router.websocket("/planner/tasks/{task_id}")
async def ws_planner_task(websocket: WebSocket, task_id: str, db: AsyncSession = Depends(get_session)) -> None:
    """规划任务实时轨迹：先快照后增量，断线由轮询兜底。"""
    user = await _user_from_ws(websocket, db)
    if user is None:
        await websocket.close(code=4401)
        return
    task = await planning_service.get_task(db, task_id, owner=user.id)
    if task is None:
        await websocket.close(code=4404)
        return

    key = f"planner:{task_id}"
    queue = hub.subscribe(key)
    await websocket.accept()
    try:
        # 快照：连接时已存在的状态与轨迹（任务可能已跑了一半/已结束）
        await _send_safe(websocket, {
            "type": "state",
            "task_id": task_id,
            "status": task.status,
            "trace": task.trace or [],
            "trip_id": task.trip_id,
            "plan": task.plan,
            "error": task.error_message,
        })
        # 增量推送：等待广播队列消息，发送失败（连接关闭）即退出
        while True:
            message = await queue.get()
            if not await _send_safe(websocket, message):
                break
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(key, queue)


# ── 协作：评论 / 投票 / 受邀编辑实时同步 ───────────────────────
@router.websocket("/trips/{trip_id}/collab")
async def ws_trip_collab(websocket: WebSocket, trip_id: str, db: AsyncSession = Depends(get_session)) -> None:
    """行程协作频道：持有分享/编辑令牌的连接实时收到评论/投票/站点变更。"""
    token = websocket.query_params.get("token") or ""
    edit = websocket.query_params.get("edit") == "1"
    # 校验令牌属于该行程（读一次库；广播用 token 维度，避免行程 id 泄露风险）
    try:
        trip = (
            await collab_service._get_trip_by_edit_token(db, token)
            if edit else await collab_service._get_trip_by_token(db, token)
        )
    except Exception:  # noqa: BLE001 — 令牌无效
        await websocket.close(code=4404)
        return
    if trip is None or trip.id != trip_id:
        await websocket.close(code=4404)
        return

    key = f"collab:{trip_id}"
    queue = hub.subscribe(key)
    await websocket.accept()
    try:
        # 增量推送：等待广播队列消息，发送失败（连接关闭）即退出
        while True:
            message = await queue.get()
            if not await _send_safe(websocket, message):
                break
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(key, queue)