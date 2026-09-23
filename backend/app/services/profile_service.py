"""用户画像服务：跨会话偏好记忆的读写 + 规划注入。

最小权限：画像只按 owner 访问，永不复用他人画像；规划注入只在创建任务时
从 DB 读一次，作为 request_data 快照落库（任务执行时不再触库）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserProfile
from app.schemas.profile import ProfileIn


async def get_profile(db: AsyncSession, *, user_id: str) -> UserProfile | None:
    """读取用户画像；未创建过画像返回 None（调用方决定默认值）。"""
    stmt = select(UserProfile).where(UserProfile.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_profile(db: AsyncSession, *, user_id: str, data: ProfileIn) -> UserProfile:
    """全量覆盖 upsert：不存在则创建，存在则整体替换字段。

    幂等：同一画像连续 PUT 相同内容结果一致；返回刷新后的 ORM。
    """
    profile = await get_profile(db, user_id=user_id)
    values = data.model_dump()
    if profile is None:
        profile = UserProfile(user_id=user_id, **values)
        db.add(profile)
    else:
        for field, value in values.items():
            setattr(profile, field, value)
    await db.flush()
    await db.refresh(profile)
    return profile


def profile_to_context(profile: UserProfile | None) -> str:
    """把画像转成给 Agent 的纯文本上下文（无画像返回空串，不注入）。"""
    if profile is None:
        return ""
    lines: list[str] = []
    if profile.traveler_type:
        lines.append(f"出行人群：{profile.traveler_type}")
    if profile.pace:
        lines.append(f"节奏偏好：{profile.pace}")
    if profile.budget_tier:
        lines.append(f"预算档：{profile.budget_tier}")
    if profile.favorite_cities:
        lines.append(f"常去城市：{'、'.join(profile.favorite_cities)}")
    prefs = profile.preferences_json or {}
    if prefs:
        try:
            import json

            lines.append(f"其它偏好：{json.dumps(prefs, ensure_ascii=False)}")
        except (TypeError, ValueError):
            lines.append(f"其它偏好：{prefs}")
    if not lines:
        return ""
    return "【跨会话用户画像】（来自该用户历史偏好，规划时请优先尊重；与本次请求冲突时以本次请求为准）\n" + "\n".join(lines)


async def profile_for_request(db: AsyncSession, *, user_id: str) -> dict[str, Any]:
    """规划任务创建时调用：读取画像并返回注入段。

    返回 {"profile_text": str}；未设置画像时 profile_text 为空串。
    """
    profile = await get_profile(db, user_id=user_id)
    return {"profile_text": profile_to_context(profile)}