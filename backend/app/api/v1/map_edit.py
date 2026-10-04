"""地图拖拽修订 API：POST /api/v1/trips/{trip_id}/map-edit。

把「拖动 marker 改坐标」落成一次最小 diff 原子应用（复用 revise 的 diff 内核）。

- 登录必需（与行程管理一致）；仅 owner 可改（与 revise 相同鉴权）；
- 坐标交给 Pydantic 范围校验（422），服务层兜底再校验（400）；
- 自驾约束门拒绝时返回 400 + detail.issues（前端提示「自驾约束前置」）；
- 站点找不到返回 404。

受邀编辑版（task-map-drag-edit 分享页接线）：POST /api/v1/trips/edit/{token}/map-edit
- 凭 edit_token 免登录（与 update_invited_stop 同信任语义）；
- ShareView 受邀编辑模式（?edit=1）下的地图拖拽使用此端点，
  避免受邀者以只读 view 身份打 owner 鉴权端点被 401 踢去登录页。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.map_edit import MapEditOut, MapEditRequest
from app.services.map_edit_service import map_edit_trip, map_edit_trip_by_token

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


@router.post(
    "/trips/edit/{token}/map-edit",
    response_model=MapEditOut,
    summary="受邀编辑地图拖拽修订：凭 edit_token 免登录移动站点坐标（同 diff 内核 + DrivingGate）",
)
async def map_edit_by_token(
    token: str,
    data: MapEditRequest,
    db: AsyncSession = Depends(get_session),
) -> MapEditOut:
    """受邀编辑者（持 edit_token）拖拽 marker 改坐标，走同一条 diff 内核。

    与 update_invited_stop 同信任语义：持有效 edit_token 即视为受邀协作授权；
    令牌过期/吊销 → 生命周期门禁 410/403；无此令牌 → 404。
    """
    result = await map_edit_trip_by_token(
        db,
        token,
        name=data.name,
        lat=data.lat,
        lng=data.lng,
        day_number=data.day_number,
    )
    return MapEditOut(**result)