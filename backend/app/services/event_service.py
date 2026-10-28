"""行程事件通知服务（task-trip-event-notify）。

目的：把「行程内发生了什么」变成可订阅/可查询的事件流——修订、打卡、跳过、
顺延、投票、评论等业务动作 append-only 记录到 ``trip_events`` 表，同时广播到
collab WS feed（复用 ``publish_collab`` 通道），owner 与受邀者实时可见。

设计契约（与 live_service / collab_service 同源）：
- **事件是事实记录（append-only），不做状态承载**——权威状态仍在 trip/stop 自身；
- ``event_type``：revise / check / skip / delay / comment / vote / edit / share；
- ``payload``：可读摘要（事件文案 key + 参数），前端可直接展示；
- 记录失败**绝不阻断主流程**（try/except + logger.debug，与 _publish 同哲学）；
- 全部为确定性操作，不经过 LLM。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import TripEvent

logger = get_logger(__name__)

EVENT_TYPES = (
    "revise", "check", "skip", "delay", "comment", "vote", "edit", "share",
    "chat_edit",
)


async def record_event(
    db: AsyncSession,
    *,
    trip_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    commit: bool = True,
) -> TripEvent | None:
    """记录一条行程事件（append-only）。失败静默降级（绝不阻断主流程）。

    Args:
        db: 数据库会话（调用方事务内传递，避免半途提交）
        trip_id: 行程 id（外键，级联删除）
        event_type: 事件类型（revise/check/skip/delay/comment/vote/edit/share）
        payload: 可读摘要（含文案 key 与参数，前端可直接展示）
        commit: 是否立即 commit（默认 True；调用方在自己事务中可传 False）
    """
    if event_type not in EVENT_TYPES:
        logger.warning("未知事件类型 %s，仍记录（可选：%s）", event_type, EVENT_TYPES)
    try:
        ev = TripEvent(
            trip_id=trip_id,
            event_type=event_type,
            payload=payload or {},
            created_at=datetime.now(timezone.utc),
        )
        db.add(ev)
        if commit:
            await db.commit()
        # 广播到 collab WS feed（无订阅为 no-op）
        _broadcast(trip_id, event_type, payload or {})
        return ev
    except Exception:  # noqa: BLE001 — 事件记录失败绝不影响业务动作
        logger.debug("行程事件记录失败: %s/%s", trip_id, event_type, exc_info=True)
        if commit:
            await db.rollback()
        return None


def _broadcast(trip_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """广播事件到 collab feed（复用 publish_collab，失败静默）。"""
    try:
        from app.services.collab_service import publish_collab

        publish_collab(trip_id, {"type": f"event.{event_type}", **payload})
    except Exception:  # noqa: BLE001
        logger.debug("collab feed 事件广播失败: %s", event_type, exc_info=True)


async def list_events(
    db: AsyncSession,
    trip_id: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[TripEvent]:
    """行程事件列表（按 created_at 倒序，最新在前，分页）。"""
    stmt = (
        select(TripEvent)
        .where(TripEvent.trip_id == trip_id)
        .order_by(TripEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def event_out(ev: TripEvent) -> dict[str, Any]:
    """事件 → 可序列化 dict（前端 feed 直接消费）。"""
    return {
        "id": ev.id,
        "trip_id": ev.trip_id,
        "event_type": ev.event_type,
        "payload": ev.payload or {},
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }