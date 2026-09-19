"""行程规划：异步任务 + 轮询查询。

POST /planner/plan → 创建任务立即返回 task_id（202）
GET  /planner/tasks/{task_id} → 轮询任务状态（pending/running/completed/failed）
任务完成后返回 trip_id / plan / trace。

优势：真实 LLM 规划可能耗时 30s+，同步接口会占满 worker；异步化后
前端可轮询展示实时 T-A-O 轨迹。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models import User
from app.schemas import PlanRequest, PlanTaskOut
from app.services import planning_service

router = APIRouter()


@router.post(
    "/plan",
    response_model=PlanTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交 AI 行程规划任务（异步）",
)
async def plan_trip(
    data: PlanRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PlanTaskOut:
    """创建规划任务并立即返回 task_id；结果通过 GET /planner/tasks/{id} 查询。"""
    task = await planning_service.create_task(db, data, owner=user.id)
    return planning_service.task_to_out(task)


@router.get("/tasks/{task_id}", response_model=PlanTaskOut, summary="查询规划任务状态")
async def get_plan_task(
    task_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PlanTaskOut:
    """轮询任务状态。完成时返回 plan / trip_id / trace。"""
    task = await planning_service.get_task(db, task_id, owner=user.id)
    if task is None:
        raise NotFoundError("规划任务不存在", code="plan_task_not_found")
    return planning_service.task_to_out(task)