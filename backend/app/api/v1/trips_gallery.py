"""公开灵感画廊 + 城市模板路由（task-gallery-featured + city-templates）。

注意：/gallery 必须声明在 /{trip_id} 之前，避免 "gallery" 被当作 trip_id 吞掉。
（聚合到 trips router 时，本 router 注册于 trips_crud 之前。）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import TripOut

router = APIRouter()


@router.get("/gallery", summary="公开灵感画廊（已发布行程摘要，免登录）")
async def list_gallery(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """精选画廊：owner 发布 + 有分享令牌的行程摘要（目的地/天数/预算/卖点）。"""
    from app.services import gallery_service

    items = await gallery_service.list_gallery(db, limit=limit, offset=offset)
    return {"items": items, "total": len(items)}


@router.get("/gallery/templates", summary="城市模板卡（23 目的地知识库，免登录）")
async def list_city_templates(
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """城市模板：目的地/建议天数/预算档/标签（规则生成，零 LLM，供深链预填创建）。"""
    from app.services import gallery_service

    items = gallery_service.city_templates(limit=limit)
    return {"items": items, "total": len(items)}


@router.post("/gallery/{source_id}/clone", response_model=TripOut, status_code=status.HTTP_201_CREATED,
             summary="以此为基础创建（复制画廊行程到我的账号）")
async def clone_gallery_trip(
    source_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TripOut:
    """复制精选行程（日程/站点全量，不含令牌与协作数据）到当前账号。"""
    from app.services import gallery_service

    trip = await gallery_service.clone_trip(db, source_id, new_owner=user.id)
    return TripOut.model_validate(trip)


@router.post("/{trip_id}/gallery/publish", summary="发布行程到灵感画廊（owner）")
async def publish_gallery_trip(
    trip_id: str,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """owner 发布：自动确保只读分享令牌存在，带一句话卖点。"""
    from app.services import gallery_service

    blurb = (payload or {}).get("blurb") if isinstance(payload, dict) else None
    return await gallery_service.publish_to_gallery(db, trip_id, owner=user.id, blurb=blurb)


@router.delete("/{trip_id}/gallery/publish", status_code=status.HTTP_204_NO_CONTENT,
               summary="从灵感画廊撤回（owner）")
async def unpublish_gallery_trip(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """owner 撤回发布（只清精选标记，不影响分享链接）。"""
    from app.services import gallery_service

    await gallery_service.unpublish_from_gallery(db, trip_id, owner=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)