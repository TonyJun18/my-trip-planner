"""规划任务恢复扫描：pending 卡死 / running 崩溃遗留 → 启动时收敛为 failed。

对应审查结论「#2 崩溃恢复只救 running，不救 pending」：
- 任务创建 = db.commit() 之后才 submit 内存队列 → 两者之间崩溃，任务永远停在 pending；
- 旧恢复扫描只处理 running，pending 超时任务轮询永不收敛 → 没有错误、没有重试。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.config import settings


async def _make_task(db: AsyncSession, *, status: str, age_seconds: int, owner: str | None = None) -> str:
    """直接插入一条指定状态的 PlanTask（不走 create_task 以模拟崩溃遗留场景）。"""
    from app.models import PlanTask

    task = PlanTask(
        owner=owner,
        request_data={"destination": "测试地", "start_date": "2026-10-05", "end_date": "2026-10-06"},
        status=status,
    )
    if status in ("running", "completed", "failed"):
        task.started_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
        task.finished_at = datetime.now(UTC)
    task.created_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task.id


@pytest.mark.asyncio
async def test_recover_marks_stale_pending_as_failed(test_engine):
    """pending 超过阈值 → 恢复扫描标记 failed（不再永远卡在排队中）。"""
    from app.services.planning_service import PlanningExecutor

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        stale_id = await _make_task(db, status="pending", age_seconds=settings.TASK_PENDING_STALE_SECONDS + 60)
        fresh_id = await _make_task(db, status="pending", age_seconds=30)
        await db.commit()

    executor = PlanningExecutor(factory)
    await executor._recover_stale_tasks()
    await executor.stop()

    async with factory() as db:
        from app.models import PlanTask

        stale = await db.get(PlanTask, stale_id)
        assert stale is not None and stale.status == "failed"
        assert stale.error_message and "pending" in stale.error_message
        fresh = await db.get(PlanTask, fresh_id)
        assert fresh is not None and fresh.status == "pending"  # 未超时 → 保持排队


@pytest.mark.asyncio
async def test_recover_marks_stale_running_as_failed(test_engine):
    """running 超过阈值（进程崩溃遗留）→ 恢复扫描标记 failed（回归保护）。"""
    from app.services.planning_service import PlanningExecutor

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        stale_id = await _make_task(db, status="running", age_seconds=settings.TASK_STALE_RUNNING_SECONDS + 60)
        fresh_id = await _make_task(db, status="running", age_seconds=30)
        await db.commit()

    executor = PlanningExecutor(factory)
    await executor._recover_stale_tasks()
    await executor.stop()

    async with factory() as db:
        from app.models import PlanTask

        stale = await db.get(PlanTask, stale_id)
        assert stale is not None and stale.status == "failed"
        fresh = await db.get(PlanTask, fresh_id)
        assert fresh is not None and fresh.status == "running"  # 未超时 → 保持 running


@pytest.mark.asyncio
async def test_recover_skips_terminal_tasks(test_engine):
    """已完成/已失败任务不受恢复扫描打扰（不重复标记）。"""
    from app.services.planning_service import PlanningExecutor

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        done_id = await _make_task(db, status="completed", age_seconds=9999)
        failed_id = await _make_task(db, status="failed", age_seconds=9999)
        await db.commit()

    executor = PlanningExecutor(factory)
    await executor._recover_stale_tasks()
    await executor.stop()

    async with factory() as db:
        from app.models import PlanTask

        assert (await db.get(PlanTask, done_id)).status == "completed"
        assert (await db.get(PlanTask, failed_id)).status == "failed"


@pytest.mark.asyncio
async def test_recover_pending_failure_close_loop_via_api(test_engine):
    """端到端：pending 卡死任务在「新 executor 启动」后被收敛，轮询拿到确定失败态。"""
    from app.services import planning_service
    from app.services.planning_service import PlanningExecutor

    # 模拟上一进程崩溃：直接造一个超时 pending（不 submit 队列）
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        stale_id = await _make_task(db, status="pending", age_seconds=settings.TASK_PENDING_STALE_SECONDS + 60)
        await db.commit()

    # 新进程 executor 启动 → 恢复扫描跑一次
    executor = PlanningExecutor(factory)
    await executor._recover_stale_tasks()
    await executor.stop()

    async with factory() as db:
        from app.models import PlanTask

        task = await db.get(PlanTask, stale_id)
        assert task is not None
        assert task.status == "failed"
        assert task.finished_at is not None