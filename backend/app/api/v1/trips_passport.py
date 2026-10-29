"""旅程护照 API（task-journey-passport：徽章墙 + 分享只读）。

端点（挂 /trips 前缀，路径字面量在 /{trip_id} 之前注册）：
- GET /trips/{trip_id}/passport        —— 行程护照（owner）
- GET /trips/share/{token}/passport    —— 分享只读护照（免登录徽章墙）

护照徽章由事件 hook 自动触发（record_event 后 maybe_award），
本模块只提供读取视图；不提供手动改徽章端点（徽章只增不减，防作弊）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import PassportOut
from app.services import passport_service, trip_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get(
    "/{trip_id}/passport",
    response_model=PassportOut,
    summary="行程护照徽章墙（owner）",
)
async def get_trip_passport(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PassportOut:
    """owner 查看行程护照（徽章墙 + 阶段 + 进度）。"""
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    passport = await passport_service.get_passport(db, trip)
    return PassportOut(**passport_service.passport_out(passport))


@router.get(
    "/share/{token}/passport",
    response_model=PassportOut,
    summary="分享页旅程护照（免登录只读）",
)
async def get_shared_passport(
    token: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> PassportOut:
    """凭 share_token 免登录查看护照徽章墙（分享页素材）。"""
    trip = await trip_service.get_trip_by_share_token(db, token, password=x_share_password, gate_token=x_share_gate)
    passport = await passport_service.get_passport(db, trip)
    return PassportOut(**passport_service.passport_out(passport))