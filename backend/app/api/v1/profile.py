"""用户画像 API：跨会话偏好记忆的读取与保存。

- GET /api/v1/profile → 当前用户画像（无画像返回空默认，不报错）
- PUT /api/v1/profile → 全量 upsert（不存在创建，存在整体替换）
- GET/POST/PUT/DELETE /api/v1/profile/preferences → 旅行记忆偏好条目
  （task-floattrip-borrow Story 2：可查看/编辑/忘记），删除后不再注入规划

规划链路注入：POST /planner/plan 创建任务时自动读取画像，把画像摘要注入
Agent 上下文（见 planning_service.create_task → profile_service.profile_for_request）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models import User
from app.schemas.preference import PreferenceItemIn, PreferenceItemOut, PreferenceListOut
from app.schemas.profile import ProfileIn, ProfileOut
from app.services import preference_item_service, profile_service

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


# ── 旅行记忆偏好条目（task-floattrip-borrow Story 2）──────────
# 可查看/编辑/删除（忘记）的长期偏好条目；删除后规划上下文不再注入。


@router.get("/preferences", response_model=PreferenceListOut, summary="读取旅行记忆偏好条目")
async def list_preferences(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PreferenceListOut:
    """返回当前用户偏好条目列表（含来源/更新时间）。无画像 → 空列表。"""
    items, total = await preference_item_service.list_items(db, user_id=user.id)
    return PreferenceListOut(items=[PreferenceItemOut(**i) for i in items], total=total)


@router.post(
    "/preferences",
    response_model=PreferenceItemOut,
    status_code=201,
    summary="新增一条旅行记忆偏好条目",
)
async def add_preference(
    data: PreferenceItemIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PreferenceItemOut:
    """新增偏好条目（用户主动声明，默认 source=user）。"""
    item = await preference_item_service.add_item(
        db, user_id=user.id, category=data.category, content=data.content, source=data.source
    )
    await db.commit()
    return PreferenceItemOut(**item)


@router.put(
    "/preferences/{item_id}",
    response_model=PreferenceItemOut,
    summary="编辑一条旅行记忆偏好条目",
)
async def update_preference(
    item_id: str,
    data: PreferenceItemIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PreferenceItemOut:
    """编辑偏好条目；不存在 → 404。"""
    item = await preference_item_service.update_item(
        db, user_id=user.id, item_id=item_id, category=data.category, content=data.content
    )
    if item is None:
        raise NotFoundError("偏好条目不存在", code="preference_item_not_found")
    await db.commit()
    return PreferenceItemOut(**item)


@router.delete(
    "/preferences/{item_id}",
    status_code=204,
    summary="删除（忘记）一条旅行记忆偏好条目",
)
async def delete_preference(
    item_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """忘记一条偏好条目；删除后规划上下文不再注入。不存在 → 404。"""
    ok = await preference_item_service.delete_item(db, user_id=user.id, item_id=item_id)
    if not ok:
        raise NotFoundError("偏好条目不存在", code="preference_item_not_found")
    await db.commit()