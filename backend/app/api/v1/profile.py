"""用户画像 API：跨会话偏好记忆的读取与保存。

- GET /api/v1/profile → 当前用户画像（无画像返回空默认，不报错）
- PUT /api/v1/profile → 全量 upsert（不存在创建，存在整体替换）

规划链路注入：POST /planner/plan 创建任务时自动读取画像，把画像摘要注入
Agent 上下文（见 planning_service.create_task → profile_service.profile_for_request）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.profile import ProfileIn, ProfileOut
from app.services import profile_service

router = APIRouter()


@router.get("", response_model=ProfileOut, summary="读取当前用户画像")
async def get_my_profile(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProfileOut:
    """返回当前用户画像；未设置过画像时返回默认空画像（不报错，前端可安全渲染）。"""
    profile = await profile_service.get_profile(db, user_id=user.id)
    if profile is None:
        # 空画像：只有归属信息，无偏好字段
        return ProfileOut(
            id="",
            user_id=user.id,
            traveler_type=None,
            pace=None,
            budget_tier=None,
            favorite_cities=None,
            preferences_json=None,
            updated_at=user.created_at,
        )
    return ProfileOut.model_validate(profile)


@router.put("", response_model=ProfileOut, summary="保存当前用户画像（全量覆盖 upsert）")
async def put_my_profile(
    data: ProfileIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProfileOut:
    """创建或整体替换当前用户画像。字段缺失即重置为空。"""
    profile = await profile_service.upsert_profile(db, user_id=user.id, data=data)
    return ProfileOut.model_validate(profile)