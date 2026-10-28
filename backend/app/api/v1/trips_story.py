"""旅程故事 API（task-trip-story：晒图高光卡生成）。

端点（挂 /trips 前缀）：
- POST /trips/{trip_id}/story  —— 生成旅程故事卡（owner；channel=xhs/moments/poster）

生成基于 journey 投影 + passport 徽章 + 费用汇总（真实数据驱动），
LLM 失败降级模板；空投影返回 empty=true 引导打卡/记账而非硬生成。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import StoryOut, StoryRequest
from app.services import journey_service, story_service, trip_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post(
    "/{trip_id}/story",
    response_model=StoryOut,
    summary="生成旅程故事卡（晒图高光卡）",
)
async def generate_trip_story(
    trip_id: str,
    data: StoryRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StoryOut:
    """owner 生成旅程故事卡（小红书/朋友圈/长图三渠道）。"""
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    projection = await journey_service.journey_projection(db, trip)
    # 注入护照徽章到投影
    from app.services import passport_service

    passport = await passport_service.get_passport(db, trip)
    projection["badges"] = passport_service.passport_out(passport)["badges"]

    story = await story_service.build_trip_story(
        trip, projection, channel=data.channel, provider=data.provider
    )
    return StoryOut(**story)