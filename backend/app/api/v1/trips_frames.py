"""相框数据投影与 AI 配文 API（frame-marketplace，trips 前缀）。

端点：
- GET /trips/{trip_id}/frames/{day_id}/data   单日打卡卡投影（owner）
- GET /trips/{trip_id}/frames/summary/data    整程总结图投影（owner）
- POST /trips/{trip_id}/frames/{day_id}/copy  AI 配文生成（owner；source 诚实标注）

⚠️ 路由顺序：/frames/summary/data 是三段精确路径，必须先于 /frames/{day_id}/data
注册（Starlette 按序匹配，否则 summary 会被当作 day_id 吞掉）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.frames import DayProjectionOut, SummaryProjectionOut
from app.services import frame_projection_service as projection
from app.services import trip_service

router = APIRouter()


async def _get_own_trip(db: AsyncSession, trip_id: str, user: User):
    """owner 限定：非 owner 统一 403（不泄露行程存在性）。"""
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    return trip


@router.get(
    "/{trip_id}/frames/summary/data",
    response_model=SummaryProjectionOut,
    summary="整程总结图数据投影（owner）",
)
async def get_summary_projection(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    trip = await _get_own_trip(db, trip_id, user)
    body = await projection.summary_projection(db, trip)
    return SummaryProjectionOut(**body)


@router.get(
    "/{trip_id}/frames/{day_id}/data",
    response_model=DayProjectionOut,
    summary="单日打卡卡数据投影（owner）",
)
async def get_day_projection(
    trip_id: str,
    day_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    trip = await _get_own_trip(db, trip_id, user)
    body = await projection.day_projection(db, trip, day_id)
    if body is None:
        raise HTTPException(status_code=404, detail="日程不存在")
    return DayProjectionOut(**body)
