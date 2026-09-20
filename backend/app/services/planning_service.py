"""规划任务服务：异步 Agent 执行 + 结果持久化回写。

职责：
1. 创建规划任务（pending）
2. 后台执行 Agent（T-A-O 循环），实时更新任务状态/trace
3. 成功后将 plan 回写成 Trip / TripDay / Stop 骨架（并保存 TripPlan 快照）
4. 失败时记录错误，可被轮询接口查询

设计说明：
- 任务执行使用 asyncio 队列 + 单 worker，避免并发打爆 LLM / Tavily / Nominatim
- 所有 DB 写入用独立 session（避免跨请求/协程共享 session）
- 幂等：每个 task 只处理一次；失败可重试（新任务）
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.agents import run_planning_agents
from app.common.config import settings
from app.core.logging import get_logger
from app.models import PlanTask, Stop, Trip, TripDay, TripPlan
from app.schemas import PlanRequest, PlanTaskOut

logger = get_logger(__name__)


# ── 任务执行器（单 worker + 队列） ────────────────────────────
class PlanningExecutor:
    """后台执行规划任务的单 worker 队列。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    def submit(self, task_id: str) -> None:
        self._queue.put_nowait(task_id)

    async def _worker_loop(self) -> None:
        """串行消费队列，逐个执行规划任务。"""
        while True:
            task_id = await self._queue.get()
            try:
                await self._execute_task(task_id)
            except Exception:
                logger.exception("规划任务执行异常 task_id=%s", task_id)
            finally:
                self._queue.task_done()

    async def _execute_task(self, task_id: str) -> None:
        """执行单个任务：更新状态 → 跑 Agent → 回写库 → 完成/失败。"""
        async with self._session_factory() as db:
            task = await db.get(PlanTask, task_id)
            if task is None:
                logger.warning("规划任务不存在 task_id=%s", task_id)
                return
            if task.status == "running":
                return  # 已在跑（幂等）
            task.status = "running"
            task.started_at = datetime.now(UTC)
            await db.commit()

            request_data = task.request_data or {}
            provider = request_data.get("provider", "auto")

            try:
                result = await run_planning_agents(
                    request_data,
                    provider=provider,
                    max_corrections=settings.AGENT_MAX_CORRECTIONS,
                    max_review_rounds=settings.AGENT_MAX_REVIEW_ROUNDS,
                )
            except Exception as exc:
                logger.exception("Agent 执行失败 task_id=%s", task_id)
                task.status = "failed"
                task.error_message = str(exc)
                task.finished_at = datetime.now(UTC)
                await db.commit()
                return

            if result.get("status") != "completed" or result.get("plan") is None:
                task.status = "failed"
                task.error_message = result.get("error") or "AI 未能生成完整行程计划"
                task.finished_at = datetime.now(UTC)
                await db.commit()
                return

            # 成功：回写行程骨架 + TripPlan 快照（原子）
            plan = result["plan"]
            try:
                trip_id = await _persist_trip(db, request_data, plan, result)
            except Exception as exc:
                logger.exception("行程回写失败 task_id=%s", task_id)
                task.status = "failed"
                task.error_message = f"行程落库失败: {exc}"
                task.finished_at = datetime.now(UTC)
                await db.commit()
                return

            task.status = "completed"
            task.provider = result.get("provider")
            task.model = result.get("model")
            task.trace = _normalize_trace(result.get("trace") or [])
            task.plan = plan
            task.trip_id = trip_id
            task.finished_at = datetime.now(UTC)
            await db.commit()

            logger.info("规划任务完成 task_id=%s trip_id=%s provider=%s days=%d agents=%s",
                        task_id, trip_id, result.get("provider"), len(plan.get("days", [])),
                        result.get("agents"))


async def _persist_trip(
    db: AsyncSession,
    request: dict[str, Any],
    plan: dict[str, Any],
    result: dict[str, Any],
) -> str:
    """把 Agent 生成的 plan 回写成 Trip / TripDay / Stop 骨架，返回 trip_id。"""
    trip = Trip(
        owner=request.get("owner"),
        title=f"{request.get('destination', '')}行程",
        destination=request.get("destination", ""),
        start_date=_parse_date(request.get("start_date")) or _today(),
        end_date=_parse_date(request.get("end_date")) or _today(),
        travelers=request.get("travelers", 1),
        budget=request.get("budget"),
        status="planning",
    )
    db.add(trip)
    await db.flush()

    for day in plan.get("days", []):
        day_record = TripDay(
            trip_id=trip.id,
            day_number=day.get("day_number", 0),
            date=_parse_date(day.get("date")),
            note=day.get("theme"),
        )
        db.add(day_record)
        await db.flush()
        for idx, stop in enumerate(day.get("stops", []), start=1):
            db.add(
                Stop(
                    day_id=day_record.id,
                    order_index=idx,
                    name=stop.get("name", ""),
                    stop_type=stop.get("type", "attraction"),
                    lat=stop.get("lat"),
                    lng=stop.get("lng"),
                    description=stop.get("description"),
                    estimated_cost=stop.get("estimated_cost"),
                    estimated_duration_minutes=stop.get("duration_minutes"),
                    # 保留来源元数据（前端地图/导出可用；将来可扩展富信息）
                    details={
                        k: stop.get(k)
                        for k in ("source", "source_url", "address", "geo", "rating")
                        if stop.get(k) is not None
                    }
                    or None,
                )
            )

    plan_record = TripPlan(
        trip_id=trip.id,
        plan_data=plan,
        trace=result.get("trace") or [],
        provider=result.get("provider"),
        model=result.get("model"),
        status="completed",
    )
    db.add(plan_record)
    await db.commit()
    return trip.id


def _parse_date(value: Any) -> date | None:
    """宽容解析日期（str / date / datetime）。"""
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _today() -> date:
    """当前日期（UTC；避免 ruff DTZ011）。"""
    return datetime.now(UTC).date()


# ── 全局执行器（在 lifespan 中启动/停止） ─────────────────────
_executor: PlanningExecutor | None = None


def get_executor(session_factory: async_sessionmaker[AsyncSession] | None = None) -> PlanningExecutor:
    """返回全局执行器。测试可传入 session_factory 覆盖（指向测试库）。"""
    global _executor
    if _executor is None:
        if session_factory is None:
            from app.core.database import SessionLocal

            session_factory = SessionLocal
        _executor = PlanningExecutor(session_factory)
    return _executor


# ── 任务 CRUD（供 API 使用） ─────────────────────────────────
async def create_task(db: AsyncSession, data: PlanRequest, *, owner: str | None = None) -> PlanTask:
    """创建规划任务并入队。"""
    request_data = data.model_dump(mode="json")  # date → ISO 字符串，可 JSON 序列化
    if owner:
        request_data["owner"] = owner
    task = PlanTask(
        owner=owner,
        request_data=request_data,
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    get_executor().submit(task.id)
    return task


async def get_task(db: AsyncSession, task_id: str, *, owner: str | None = None) -> PlanTask | None:
    """查询任务（校验 owner 权限；None 代表匿名身份，匹配 owner IS NULL）。"""
    stmt = select(PlanTask).where(PlanTask.id == task_id)
    if owner is None:
        stmt = stmt.where(PlanTask.owner.is_(None))
    else:
        stmt = stmt.where(PlanTask.owner == owner)
    return (await db.execute(stmt)).scalar_one_or_none()


def task_to_out(task: PlanTask) -> PlanTaskOut:
    """ORM → API 响应。"""
    return PlanTaskOut(
        task_id=task.id,
        status=task.status,  # type: ignore[arg-type]
        provider=task.provider,
        model=task.model,
        created_at=task.created_at,
        finished_at=task.finished_at,
        trip_id=task.trip_id,
        error=task.error_message,
        trace=task.trace,
        plan=task.plan,
    )


def _normalize_trace(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把多 Agent 的 trace 步骤（含 agent 名）转成前端兼容的 AgentTraceStep 结构。

    {agent, action, observation, status} → {thought: agent, action, observation}。
    """
    out = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        out.append({
            "thought": s.get("agent") or s.get("thought") or "",
            "action": s.get("action") or "",
            "action_input": "",
            "observation": s.get("observation") or "",
        })
    return out