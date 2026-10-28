"""旅程追踪 API（task-journey-timeline：旅程全程追踪投影）。

端点（挂 /trips 前缀，路径字面量在 /{trip_id} 之前注册）：
- GET /trips/{trip_id}/journey —— 旅程投影（打卡进度/按天状态/费用/预订/高光）

读时聚合（零新表），owner 视角。分享/编辑 token 的只读投影在 trips_share 里
（分享视图只透出打卡进度与高光，不含费用/凭证等财务数据）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import JourneyOut
from app.services import journey_service, trip_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get(
    "/{trip_id}/journey",
    response_model=JourneyOut,
    summary="旅程全程追踪投影（owner）",
)
async def get_trip_journey(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JourneyOut:
    """owner 查看行程的旅程追踪：打卡进度/按天状态/费用汇总/预订状态/高光。"""
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    projection = await journey_service.journey_projection(db, trip)
    return JourneyOut(**projection)