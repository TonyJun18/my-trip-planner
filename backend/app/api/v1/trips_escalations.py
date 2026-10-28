"""人工兜底评审队列路由（task-human-escalation-eval）。

/escalations 必须声明在 /{trip_id} 之前，避免 "escalations" 被当作 trip_id 吞掉。
（聚合到 trips router 时，本 router 注册于 trips_crud 之前。）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import EscalationListOut

router = APIRouter()


@router.get("/escalations", response_model=EscalationListOut, summary="需人工复核的行程（评审队列，owner）")
async def list_escalations(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EscalationListOut:
    """owner 的评审队列：最新 AI plan 的 quality 命中「需人工复核」信号的行程。

    信号派生（不存储）：finalized=true（达最大评审轮强制定稿）/ passed=false
    （Critic 或修订复核未通过）/ degraded=true（Critic 调用失败降级通过）。
    返回结构化失败摘要（reason/summary/issues/score），自托管者可自行接人工。
    只读查询，不阻塞任何流程，不发送任何通知（诚实标注，不假装有人）。
    """
    from app.services import escalation_service

    items, total = await escalation_service.list_escalations(
        db, owner=user.id, offset=offset, limit=limit,
    )
    return EscalationListOut(items=items, total=total)