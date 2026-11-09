"""小红书发布任务编排（异步 job + 状态机 + 单浏览器串行）。

为什么不放在请求里同步跑：
半自动发布要起浏览器、等图片上传、等页面渲染，动辄十几秒到一分钟。
HTTP 请求只负责"建任务 → 立刻返回 job_id"，前端轮询状态（与规划任务同构）。

为什么是**单浏览器串行**：一个小红书账号同时只能有一个网页端会话，
并发发布会互相踢掉、也会显著抬升风控概率。用进程级信号量串起来，
代价是排队，收益是稳定。

状态机（诚实口径，不提前宣布成功）：

    queued → running → ready      半自动：表单已填好，等人点发布
                     → published  自动：点了发布且有回执
                     → unknown    点了发布但没读到回执
                     → failed     校验/登录/页面结构等失败（带 reason）
                     → manual     手动通道（不在服务端投递）
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.publishers import PublishError, XhsNote, factory
from app.services.publishers.base import PublishResult

logger = logging.getLogger(__name__)

_MAX_JOBS = 50
_jobs: OrderedDict[str, PublishJob] = OrderedDict()
_tasks: set[asyncio.Task] = set()
_sem: asyncio.Semaphore | None = None
_sem_loop: asyncio.AbstractEventLoop | None = None

TERMINAL_STATES = {"ready", "published", "unknown", "failed", "manual"}


@dataclass
class PublishJob:
    job_id: str
    trip_id: str
    mode: str
    title: str
    state: str = "queued"
    submitted: bool = False
    reason: str | None = None
    message: str | None = None
    note_url: str | None = None
    screenshot: str | None = None
    asset_ids: list[str] = field(default_factory=list)
    asset_paths: list[str] = field(default_factory=list)
    auto_submit: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "trip_id": self.trip_id,
            "channel": "xhs",
            "mode": self.mode,
            "state": self.state,
            "submitted": self.submitted,
            "reason": self.reason,
            "message": self.message,
            "note_url": self.note_url,
            "screenshot": self.screenshot,
            "asset_ids": list(self.asset_ids),
            "auto_submit": self.auto_submit,
            "hint_key": (self.meta or {}).get("hint_key"),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def _semaphore() -> asyncio.Semaphore:
    """进程级单并发信号量（按 event loop 重建，避免跨 loop 复用报错）。"""
    global _sem, _sem_loop
    loop = asyncio.get_running_loop()
    if _sem is None or _sem_loop is not loop:
        _sem = asyncio.Semaphore(1)
        _sem_loop = loop
    return _sem


def _prune() -> None:
    while len(_jobs) > _MAX_JOBS:
        old_id, _ = _jobs.popitem(last=False)
        logger.debug("发布任务历史裁剪 job_id=%s", old_id)


async def create_and_dispatch(
    *,
    trip_id: str,
    note: XhsNote,
    asset_ids: list[str],
    asset_paths: list[str],
    mode: str | None = None,
    auto_submit: bool = False,
) -> PublishJob:
    """建任务并后台执行，立刻返回（前端拿 job_id 轮询）。"""
    resolved = factory.resolve_mode(mode)
    job = PublishJob(
        job_id=uuid.uuid4().hex,
        trip_id=trip_id,
        mode=resolved,
        title=note.title,
        asset_ids=list(asset_ids),
        asset_paths=list(asset_paths),
        auto_submit=bool(auto_submit),
    )
    _jobs[job.job_id] = job
    _prune()
    task = asyncio.create_task(_run(job, note), name=f"xhs-publish-{job.job_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


def get_job(job_id: str) -> PublishJob | None:
    return _jobs.get(job_id)


def reset_for_tests() -> None:
    _jobs.clear()
    _tasks.clear()


async def _run(job: PublishJob, note: XhsNote) -> None:
    started = time.monotonic()
    job.state = "running"
    job.updated_at = datetime.now(UTC)
    publisher = factory.create(job.mode)
    try:
        async with _semaphore():
            result = await publisher.publish_note(
                note,
                job.asset_paths,
                auto_submit=job.auto_submit,
            )
        _apply_result(job, result)
    except PublishError as exc:
        job.state = "failed"
        job.reason = exc.reason
        job.message = exc.message
    except Exception as exc:  # 兜住一切，任务不能悬在 running
        logger.exception("xhs 发布任务异常 job_id=%s", job.job_id)
        job.state = "failed"
        job.reason = "internal_error"
        job.message = f"发布任务异常：{exc}"
    finally:
        job.updated_at = datetime.now(UTC)
        logger.info(
            "xhs 发布任务结束 job=%s mode=%s state=%s reason=%s 用时=%.1fs",
            job.job_id,
            job.mode,
            job.state,
            job.reason,
            time.monotonic() - started,
        )


def _apply_result(job: PublishJob, result: PublishResult) -> None:
    job.state = result.state
    job.submitted = result.submitted
    job.reason = result.reason
    job.message = result.message
    job.note_url = result.note_url
    job.screenshot = result.screenshot
    job.meta = dict(result.meta or {})
