"""行程规划：异步任务 + 轮询查询。

POST /planner/plan → 创建任务立即返回 task_id（202）
GET  /planner/tasks/{task_id} → 轮询任务状态（pending/running/completed/failed）
任务完成后返回 trip_id / plan / trace。

优势：真实 LLM 规划可能耗时 30s+，同步接口会占满 worker；异步化后
前端可轮询展示实时 T-A-O 轨迹。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.i18n import normalize_locale
from app.models import User
from app.schemas import PlanQuotaOut, PlanRequest, PlanTaskOut
from app.services import planning_service, quota_service

router = APIRouter()


@router.get(
    "/quota",
    response_model=PlanQuotaOut,
    summary="查询我的规划额度快照（24h 软阈值，只提示不拦截）",
)
async def get_plan_quota(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PlanQuotaOut:
    """最近 24h 规划次数 + 参考阈值。

    本接口只返回数据，**不做拦截**：硬配额/限流需要产品决策（见
    ``docs/nightly/evaluations/task-quota-governance-eval-2026-11-08.md``），
    当前版本由前端据此给软提示，提交永远放行。
    """
    data = await quota_service.snapshot(db, user.id)
    return PlanQuotaOut(**data)


@router.post(
    "/plan",
    response_model=PlanTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交 AI 行程规划任务（异步）",
)
async def plan_trip(
    data: PlanRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PlanTaskOut:
    """创建规划任务并立即返回 task_id；结果通过 GET /planner/tasks/{id} 查询。

    语言契约：请求显式传 ``language`` 优先生效；未传时从
    ``Accept-Language`` 头解析（normalize_locale 宽松归一，未知回退 zh-CN）。
    """
    if not data.language:
        # 显式字段优先；否则按请求头解析（前端语言切换信号在此落到后端契约）
        data.language = normalize_locale(request.headers.get("accept-language"))
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