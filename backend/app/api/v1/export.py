"""行程导出端点（task-export-offline + task-ics-export）。

四条访问路径，与详情/分享读取同信任语义：
- GET /trips/{trip_id}/export          —— owner（JWT 归属校验），完整 JSON 备份
- GET /trips/share/{token}/export      —— 持分享令牌免登录只读（含生命周期门禁）
- GET /trips/{trip_id}/export/ics      —— owner 导出 ICS 日历
- GET /trips/share/{token}/export/ics  —— 分享令牌免登录导出 ICS 日历
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.services import export_service, trip_service

router = APIRouter()


def _ics_response(content: str, trip_id: str) -> Response:
    """ICS 文本响应：text/calendar + 附件下载（文件名保持 ASCII，避免头部编码问题）。"""
    return Response(
        content=content.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="trip-{trip_id[:8]}.ics"'},
    )


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
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """凭 share_token 免登录导出（只读数据快照；与分享读取同信任语义）。"""
    trip = await trip_service.get_trip_by_share_token(db, token, password=x_share_password, gate_token=x_share_gate)
    plan = await trip_service.get_plan_by_trip_id(db, trip.id)
    plan_data = await trip_service.ensure_plan_transport(db, trip, plan) or {}
    return export_service.build_trip_export(trip, plan_data=plan_data)


@router.get("/{trip_id}/export/ics", summary="导出行程 ICS 日历（owner）")
async def export_trip_ics(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """owner 导出 .ics：每个站点一个全天事件，可直接订阅进手机/桌面日历。"""
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    return _ics_response(export_service.build_trip_ics(trip), trip.id)


@router.get("/share/{token}/export/ics", summary="导出行程 ICS 日历（免登录，凭 share_token 只读）")
async def export_shared_trip_ics(
    token: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """分享令牌免登录导出 .ics（与分享读取同生命周期门禁）。"""
    trip = await trip_service.get_trip_by_share_token(db, token, password=x_share_password, gate_token=x_share_gate)
    return _ics_response(export_service.build_trip_ics(trip), trip.id)