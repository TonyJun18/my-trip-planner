"""规划额度治理最小版（task-quota-governance-eval）：纯函数 + 窗口统计 + API。

覆盖：
- ``quota_service.summarize`` 的阈值语义（低于 / 达到 / 超过 / 负数 / 自定义窗口）
- ``quota_service.snapshot`` 只统计「本人 + 窗口内」的 ``plan_tasks``，并给出 resets_at
- ``GET /planner/quota`` 未登录 401、登录后反映真实次数、达阈值置位
- **软阈值不拦截**：额度已达上限时 ``POST /planner/plan`` 仍返回 202 并正常入队
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlanTask
from app.services import quota_service


async def _add_task(db: AsyncSession, owner: str, created_at: datetime | None = None) -> PlanTask:
    """直接落一条规划任务（不触发执行器，避免跑真实 Agent）。"""
    task = PlanTask(owner=owner, request_data={"destination": "杭州"}, status="completed")
    if created_at is not None:
        task.created_at = created_at
    db.add(task)
    await db.commit()
    return task


# ── 纯函数：阈值语义 ──────────────────────────────────────────
def test_summarize_below_limit():
    s = quota_service.summarize(used=3)
    assert s["used"] == 3
    assert s["limit"] == quota_service.SOFT_LIMIT
    assert s["remaining"] == quota_service.SOFT_LIMIT - 3
    assert s["soft_limit_reached"] is False
    assert s["window_hours"] == quota_service.WINDOW_HOURS
    assert s["resets_at"] is None


def test_summarize_at_and_over_limit():
    at = quota_service.summarize(used=quota_service.SOFT_LIMIT)
    assert at["remaining"] == 0
    assert at["soft_limit_reached"] is True

    over = quota_service.summarize(used=quota_service.SOFT_LIMIT + 7)
    assert over["remaining"] == 0  # 不返回负数
    assert over["soft_limit_reached"] is True


def test_summarize_clamps_and_custom_window():
    s = quota_service.summarize(used=-2, limit=2, window_hours=6)
    assert s["used"] == 0
    assert s["remaining"] == 2
    assert s["window_hours"] == 6


# ── 服务层：窗口 + owner 隔离 ────────────────────────────────
@pytest.mark.asyncio
async def test_snapshot_counts_only_owner_within_window(db_session: AsyncSession):
    now = datetime.now(UTC)
    await _add_task(db_session, "u-1", now - timedelta(hours=1))
    await _add_task(db_session, "u-1", now - timedelta(hours=23))
    await _add_task(db_session, "u-1", now - timedelta(hours=25))  # 窗口外
    await _add_task(db_session, "u-2", now - timedelta(hours=1))   # 他人

    snap = await quota_service.snapshot(db_session, "u-1", now=now)
    assert snap["used"] == 2
    assert snap["remaining"] == quota_service.SOFT_LIMIT - 2
    assert snap["soft_limit_reached"] is False

    # resets_at = 最早一次（23h 前）+ 24h 窗口
    expected = now - timedelta(hours=23) + timedelta(hours=24)
    assert snap["resets_at"] is not None
    assert abs((snap["resets_at"] - expected).total_seconds()) < 5


@pytest.mark.asyncio
async def test_snapshot_empty_owner(db_session: AsyncSession):
    snap = await quota_service.snapshot(db_session, "nobody")
    assert snap["used"] == 0
    assert snap["remaining"] == quota_service.SOFT_LIMIT
    assert snap["soft_limit_reached"] is False
    assert snap["resets_at"] is None


# ── API ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_quota_api_requires_login(client: AsyncClient):
    resp = await client.get("/api/v1/planner/quota")
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_quota_api_reflects_recent_tasks(client: AsyncClient, auth_user, db_session: AsyncSession):
    user, headers = auth_user
    await _add_task(db_session, user["id"], datetime.now(UTC) - timedelta(hours=2))

    resp = await client.get("/api/v1/planner/quota", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used"] == 1
    assert body["limit"] == quota_service.SOFT_LIMIT
    assert body["remaining"] == quota_service.SOFT_LIMIT - 1
    assert body["window_hours"] == quota_service.WINDOW_HOURS
    assert body["soft_limit_reached"] is False
    assert body["resets_at"] is not None


@pytest.mark.asyncio
async def test_quota_api_flags_soft_limit(client: AsyncClient, auth_user, db_session: AsyncSession):
    user, headers = auth_user
    for _ in range(quota_service.SOFT_LIMIT):
        await _add_task(db_session, user["id"], datetime.now(UTC) - timedelta(hours=3))

    body = (await client.get("/api/v1/planner/quota", headers=headers)).json()
    assert body["used"] == quota_service.SOFT_LIMIT
    assert body["remaining"] == 0
    assert body["soft_limit_reached"] is True


@pytest.mark.asyncio
async def test_plan_submission_not_blocked_by_soft_limit(
    client: AsyncClient, auth_user, db_session: AsyncSession, monkeypatch,
):
    """软阈值只提示：达到上限后提交仍然 202 入队（硬限流需用户立项）。"""
    user, headers = auth_user
    for _ in range(quota_service.SOFT_LIMIT + 1):
        await _add_task(db_session, user["id"], datetime.now(UTC) - timedelta(hours=1))

    quota = (await client.get("/api/v1/planner/quota", headers=headers)).json()
    assert quota["soft_limit_reached"] is True

    # 阻断执行器：本用例只验证端点不因额度拒绝请求，不需要真跑 Agent
    from app.services import planning_service

    submitted: list[str] = []
    monkeypatch.setattr(planning_service.get_executor(), "submit", submitted.append)

    today = datetime.now(UTC).date()
    resp = await client.post(
        "/api/v1/planner/plan",
        json={
            "destination": "杭州",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=1)).isoformat(),
            "travelers": 2,
            "budget": 2000,
            "preferences": ["美食"],
        },
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    assert submitted, "任务应照常入队（软阈值不拦截）"
