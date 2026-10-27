"""行程导出端点（task-export-offline）。

两条访问路径，与详情/分享读取同信任语义：
- GET /trips/{trip_id}/export        —— owner（JWT 归属校验）
- GET /trips/share/{token}/export    —— 持分享令牌免登录只读（含生命周期门禁）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.services import export_service, trip_service

router = APIRouter()


@router.get("/{trip_id}/export", summary="导出行程 JSON（owner，完整数据备份）")
async def export_trip(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """owner 导出行程完整 JSON（含日程/预算/质检摘要/规划上下文）。"""
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    plan = await trip_service.get_plan_by_trip_id(db, trip.id)
    plan_data = await trip_service.ensure_plan_transport(db, trip, plan) or {}
    return export_service.build_trip_export(trip, plan_data=plan_data)


@router.get("/share/{token}/export", summary="导出行程 JSON（免登录，凭 share_token 只读）")
async def export_shared_trip(
    token: str,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """持分享令牌免登录导出（与 GET /share/{token} 同信任语义，只读快照）。"""
    trip = await trip_service.get_trip_by_share_token(db, token)
    plan = await trip_service.get_plan_by_trip_id(db, trip.id)
    plan_data = await trip_service.ensure_plan_transport(db, trip, plan) or {}
    return export_service.build_trip_export(trip, plan_data=plan_data)