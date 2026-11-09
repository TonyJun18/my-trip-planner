"""本机发布器（浏览器扩展）任务服务。

设计要点（这就是"服务器不碰账号"的落点）：

- 服务端**只存任务**：标题/正文/话题/图片（图片走已有的 owner 鉴权接口）；
- 用户浏览器里的扩展持自己的登录态去填表、点发布，然后回写结果；
- 选择器由服务端下发（`selector_bundle`），小红书改版时**改一处、扩展不用重发**；
- 任务有 TTL：过期自动 `expired`，避免用户装了扩展后被推送几天前的旧任务。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trip, User, XhsPublishTask
from app.services.publishers import PublishError, XhsNote

logger = logging.getLogger(__name__)

TASK_STATES = ("pending", "claimed", "filled", "published", "failed", "expired", "cancelled")
TERMINAL = {"published", "failed", "expired", "cancelled"}
CLAIMABLE = {"pending"}

# 浏览器侧（普通 DOM）选择器：扩展直接执行，不依赖 Playwright 的 text=/has-text 引擎。
# 与 driver 的 SELECTORS 同源同版本；小红书改版时**两边一起改**，扩展无需重新发布。
WEB_SELECTORS: dict[str, list[dict[str, str]]] = {
    "image_tab": [
        {"css": "div.creator-tab", "text": "上传图文"},
        {"text": "上传图文"},
    ],
    "file_input": [
        {"css": "input[type='file'][accept*='png']"},
        {"css": "input[type='file'][accept*='jpg']"},
        {"css": "input[type='file'][accept*='image']"},
        {"css": "input.upload-input"},
    ],
    "title": [
        {"css": "input[placeholder*='标题']"},
        {"css": "input[class*='d-text']"},
    ],
    "editor": [
        {"css": "div.tiptap.ProseMirror"},
        {"css": "div[contenteditable='true']"},
    ],
    "submit_bar": [
        {"css": "xhs-publish-btn[is-publish='true']"},
        {"css": "xhs-publish-btn[is-publish]"},
        {"css": "xhs-publish-btn"},
    ],
    "overlay_close": [{"text": "我知道了"}, {"css": ".feature-guide__close"}],
    "success_marker": [{"text": "发布成功"}, {"text": "笔记已发布"}],
}


def ttl_minutes() -> int:
    from app.common.config import settings

    return max(1, int(getattr(settings, "XHS_AGENT_TASK_TTL_MINUTES", 30) or 30))


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_tz(value: datetime | None) -> datetime | None:
    """Postgres 取回的 datetime 有时是 naive（测试库/驱动差异），统一按 UTC 看待。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def selector_bundle() -> dict[str, Any]:
    """把当前选择器声明式下发（服务端单一真相，扩展不写死 CSS）。

    扩展只需要按 `selectors` 里的候选顺序找元素、按 `publish_url` 打开页面、
    按 `body_template` 拼正文；页面改版时改后端常量即可，无需重新发布扩展。
    """
    from app.services.publishers.drivers.playwright_creator import (
        CREATOR_PUBLISH_URL,
        PUBLISH_BUTTON_X_RATIO,
        SELECTOR_SET_VERSION,
        SELECTORS,
    )

    return {
        "version": SELECTOR_SET_VERSION,
        "publish_url": CREATOR_PUBLISH_URL,
        "publish_button_x_ratio": PUBLISH_BUTTON_X_RATIO,
        "selectors": {k: list(v) for k, v in SELECTORS.items() if isinstance(v, list)},
        "web": WEB_SELECTORS,
        "body_template": "{body}\n\n{topics}",
        "topic_prefix": "#",
    }


async def expire_stale(db: AsyncSession, user_id: str | None = None) -> int:
    """把超过 TTL 的未完成任务标记为 expired，返回受影响条数。"""
    deadline = _now() - timedelta(minutes=ttl_minutes())
    stmt = select(XhsPublishTask).where(
        XhsPublishTask.state.in_(("pending", "claimed", "filled")),
        XhsPublishTask.created_at < deadline,
    )
    if user_id:
        stmt = stmt.where(XhsPublishTask.user_id == user_id)
    rows = (await db.execute(stmt)).scalars().all()
    for task in rows:
        task.state = "expired"
        task.reason = "expired"
        task.message = "任务超时未完成，请重新发起发布"
        task.completed_at = _now()
    if rows:
        await db.flush()
        logger.info("xhs agent: 过期任务 %s 条", len(rows))
    return len(rows)


async def create_task(
    db: AsyncSession,
    *,
    user_id: str,
    trip_id: str,
    note: XhsNote,
    asset_ids: list[str],
) -> XhsPublishTask:
    """建任务（同一行程的旧 pending 任务自动作废，避免用户收到多条重复）。"""
    stale = (
        await db.execute(
            select(XhsPublishTask).where(
                XhsPublishTask.user_id == user_id,
                XhsPublishTask.trip_id == trip_id,
                XhsPublishTask.state == "pending",
            )
        )
    ).scalars()
    for old in stale:
        old.state = "cancelled"
        old.reason = "superseded"
        old.completed_at = _now()

    task = XhsPublishTask(
        user_id=user_id,
        trip_id=trip_id,
        title=note.title,
        body=note.body,
        topics=list(note.topics or []),
        asset_ids=list(asset_ids),
        state="pending",
    )
    db.add(task)
    await db.flush()
    logger.info("xhs agent: 建任务 id=%s user=%s trip=%s", task.id, user_id, trip_id)
    return task


async def list_tasks(
    db: AsyncSession, *, user_id: str, state: str | None = None, limit: int = 20
) -> list[XhsPublishTask]:
    await expire_stale(db, user_id)
    stmt = select(XhsPublishTask).where(XhsPublishTask.user_id == user_id)
    if state:
        stmt = stmt.where(XhsPublishTask.state == state)
    stmt = stmt.order_by(XhsPublishTask.created_at.desc()).limit(max(1, min(limit, 50)))
    return list((await db.execute(stmt)).scalars().all())


async def get_task(db: AsyncSession, *, user_id: str, task_id: str) -> XhsPublishTask:
    task = await db.get(XhsPublishTask, task_id)
    if task is None or task.user_id != user_id:
        # 不泄露"存在但不属于你"
        raise PublishError("task_not_found", "发布任务不存在")
    return task


async def claim(
    db: AsyncSession, *, user_id: str, task_id: str, agent: str | None = None
) -> XhsPublishTask:
    """领取任务：只有 pending 能领，重复领取返回当前状态（幂等）。"""
    task = await get_task(db, user_id=user_id, task_id=task_id)
    if task.state in ("claimed", "filled"):
        return task
    if task.state not in CLAIMABLE:
        raise PublishError("task_not_claimable", f"任务状态为 {task.state}，不能领取")
    task.state = "claimed"
    task.agent = (agent or "")[:128] or None
    task.claimed_at = _now()
    await db.flush()
    logger.info("xhs agent: 领取任务 id=%s agent=%s", task.id, task.agent)
    return task


async def report(
    db: AsyncSession,
    *,
    user_id: str,
    task_id: str,
    state: str,
    note_url: str | None = None,
    reason: str | None = None,
    message: str | None = None,
) -> XhsPublishTask:
    """扩展回写结果。只允许前进，不允许把已完成任务改回 pending。"""
    if state not in TASK_STATES:
        raise PublishError("bad_state", f"未知任务状态：{state}")
    task = await get_task(db, user_id=user_id, task_id=task_id)
    if task.state in TERMINAL and state != task.state:
        raise PublishError("task_closed", f"任务已结束（{task.state}），不能再改成 {state}")
    task.state = state
    if note_url:
        task.note_url = note_url[:512]
    if reason:
        task.reason = reason[:64]
    if message:
        task.message = message[:2000]
    if state in TERMINAL:
        task.completed_at = _now()
    await db.flush()
    logger.info("xhs agent: 回写任务 id=%s state=%s reason=%s", task.id, state, reason)
    return task


def to_payload(task: XhsPublishTask) -> dict[str, Any]:
    """给扩展的任务载荷（图片用 owner 鉴权接口，绝不暴露公网直链）。"""
    asset_ids = list(task.asset_ids or [])
    return {
        "task_id": task.id,
        "trip_id": task.trip_id,
        "state": task.state,
        "title": task.title,
        "body": task.body,
        "topics": list(task.topics or []),
        "images": [
            {
                "asset_id": asset_id,
                "url": f"/api/v1/trips/{task.trip_id}/xhs-assets/{asset_id}",
            }
            for asset_id in asset_ids
        ],
        "note_url": task.note_url,
        "reason": task.reason,
        "message": task.message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def to_public(task: XhsPublishTask) -> dict[str, Any]:
    """给前端轮询的状态（不含正文，减少无谓传输）。"""
    return {
        "job_id": task.id,
        "trip_id": task.trip_id,
        "channel": "xhs",
        "mode": "agent",
        "state": _front_state(task.state),
        "submitted": task.state == "published",
        "reason": task.reason,
        "message": task.message,
        "note_url": task.note_url,
        "asset_ids": list(task.asset_ids or []),
        "auto_submit": False,
        "hint_key": "xhsNote.publishAgentHint",
        "created_at": (_ensure_tz(task.created_at) or _now()).isoformat(),
        "updated_at": (_ensure_tz(task.updated_at) or _now()).isoformat(),
    }


def _front_state(state: str) -> str:
    """任务状态 → 前端既有状态词（避免前端再学一套状态机）。"""
    return {
        "pending": "pending_agent",
        "claimed": "running",
        "filled": "ready",
        "published": "published",
        "failed": "failed",
        "expired": "failed",
        "cancelled": "failed",
    }.get(state, "unknown")


async def get_trip_owner_name(db: AsyncSession, trip_id: str) -> str | None:  # pragma: no cover
    """调试辅助：任务列表里显示行程名（当前未在 API 暴露）。"""
    trip = await db.get(Trip, trip_id)
    if trip is None:
        return None
    user = await db.get(User, trip.owner) if trip.owner else None
    return user.display_name if user else None
