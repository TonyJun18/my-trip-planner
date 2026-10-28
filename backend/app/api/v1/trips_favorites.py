"""收藏灵感夹路由（task-share-token-lifecycle：登录用户收藏他人分享的行程）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models import Trip, User
from app.schemas import FavoriteListOut, FavoriteOut
from app.services import share_lifecycle

router = APIRouter()


@router.get("/favorites", response_model=FavoriteListOut, summary="我的收藏灵感夹")
async def list_favorites(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FavoriteListOut:
    """当前用户的收藏列表（倒序，含行程摘要 + share_token 便于直接打开分享页）。"""
    favorites = await share_lifecycle.list_favorites(db, user)
    items: list[FavoriteOut] = []
    for fav in favorites:
        trip = await db.get(Trip, fav.trip_id)
        if trip is None:
            continue
        items.append(
            FavoriteOut(
                id=fav.id,
                trip_id=fav.trip_id,
                title=trip.title,
                destination=trip.destination,
                start_date=trip.start_date,
                end_date=trip.end_date,
                share_token=trip.share_token,
                created_at=fav.created_at,
            )
        )
    return FavoriteListOut(items=items[offset : offset + limit], total=len(items))


@router.post(
    "/favorites/{trip_id}",
    response_model=FavoriteOut,
    summary="收藏一条行程（幂等）",
)
async def add_favorite(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FavoriteOut:
    """登录用户收藏指定行程（收藏的是只读引用，不复制行程）。"""
    fav = await share_lifecycle.add_favorite(db, trip_id, user)
    trip = await db.get(Trip, fav.trip_id)
    if trip is None:
        raise NotFoundError("行程不存在", code="trip_not_found")
    return FavoriteOut(
        id=fav.id,
        trip_id=fav.trip_id,
        title=trip.title,
        destination=trip.destination,
        start_date=trip.start_date,
        end_date=trip.end_date,
        share_token=trip.share_token,
        created_at=fav.created_at,
    )


@router.delete(
    "/favorites/{trip_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="取消收藏（幂等）",
)
async def remove_favorite(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """取消收藏（未收藏为 no-op）。"""
    await share_lifecycle.remove_favorite(db, trip_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)