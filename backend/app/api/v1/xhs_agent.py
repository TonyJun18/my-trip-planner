"""本机发布器（浏览器扩展）接口。

服务端在这里**只做三件事**：下发任务、记录状态、下发选择器。
用户的账号登录态始终留在用户自己的浏览器里，服务端不接触、不存储。

鉴权：与前端同一套 JWT（`Authorization: Bearer <token>`）。扩展首次配置时
粘贴一次 token 即可（后续可升级成短时配对码，见 docs）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import PublishRejectedError
from app.models import User
from app.schemas import XhsAgentClaimIn, XhsAgentResultIn
from app.services import xhs_agent_service
from app.services.publishers import PublishError

router = APIRouter()


def _reject(exc: PublishError) -> PublishRejectedError:
    return PublishRejectedError(exc.message, code=exc.reason, detail={"reason": exc.reason})


@router.get("/selectors", summary="下发当前页面选择器（扩展不写死 CSS）")
async def get_selectors(user: User = Depends(get_current_user)) -> dict:
    """小红书改版时只改后端常量，扩展下次轮询自动拿到新版本，无需重新发布。"""
    return xhs_agent_service.selector_bundle()


@router.get("/tasks", summary="列出待处理/最近任务")
async def list_tasks(
    state: str | None = Query(None, description="pending / claimed / filled / published / failed"),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    tasks = await xhs_agent_service.list_tasks(db, user_id=user.id, state=state, limit=limit)
    return {
        "items": [xhs_agent_service.to_payload(t) for t in tasks],
        "selectors_version": xhs_agent_service.selector_bundle()["version"],
    }


@router.post(
    "/tasks/{task_id}/claim",
    status_code=status.HTTP_200_OK,
    summary="领取任务（幂等）",
)
async def claim_task(
    task_id: str,
    data: XhsAgentClaimIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        task = await xhs_agent_service.claim(db, user_id=user.id, task_id=task_id, agent=data.agent)
    except PublishError as exc:
        raise _reject(exc) from exc
    return {
        "task": xhs_agent_service.to_payload(task),
        "selectors": xhs_agent_service.selector_bundle(),
    }


@router.post("/tasks/{task_id}/result", summary="回写结果（filled / published / failed）")
async def report_task(
    task_id: str,
    data: XhsAgentResultIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        task = await xhs_agent_service.report(
            db,
            user_id=user.id,
            task_id=task_id,
            state=data.state,
            note_url=data.note_url,
            reason=data.reason,
            message=data.message,
        )
    except PublishError as exc:
        raise _reject(exc) from exc
    return {"task_id": task.id, "state": task.state, "note_url": task.note_url}


@router.get("/tasks/{task_id}", summary="任务详情（前端轮询用）")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        task = await xhs_agent_service.get_task(db, user_id=user.id, task_id=task_id)
    except PublishError as exc:
        raise _reject(exc) from exc
    return xhs_agent_service.to_public(task)
