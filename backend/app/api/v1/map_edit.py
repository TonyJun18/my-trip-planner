"""地图拖拽修订 API：POST /api/v1/trips/{trip_id}/map-edit。

把「拖动 marker 改坐标」落成一次最小 diff 原子应用（复用 revise 的 diff 内核）。

- 登录必需（与行程管理一致）；仅 owner 可改（与 revise 相同鉴权）；
- 坐标交给 Pydantic 范围校验（422），服务层兜底再校验（400）；
- 自驾约束门拒绝时返回 400 + detail.issues（前端提示「自驾约束前置」）；
- 站点找不到返回 404。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.map_edit import MapEditOut, MapEditRequest
from app.services.map_edit_service import map_edit_trip

router = APIRouter()


@router.post(
    "/trips/{trip_id}/map-edit",
    response_model=MapEditOut,
    summary="地图拖拽修订：移动站点坐标（最小 diff 原子应用，DrivingGate 约束门前置）",
)
async def map_edit(
    trip_id: str,
    data: MapEditRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MapEditOut:
    """地图拖拽 → 站点坐标修改（op=replace 最小 diff，走统一 diff 内核）。"""
    result = await map_edit_trip(
        db,
        trip_id,
        name=data.name,
        lat=data.lat,
        lng=data.lng,
        day_number=data.day_number,
        owner=user.id,
    )
    return MapEditOut(**result)