"""行程评分 / 信任信号路由（task-trip-rating-signal）。

注意：/ratings/summary 与 /gallery 一样是字面量段，必须注册在 trips_crud
的 /{trip_id} 之前（否则 "ratings" 会被当作 trip_id 吞掉 → 404）。
本 router 在 api/v1/__init__.py 中注册于 trips_crud 之前。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_user
from app.core.database import get_session
from app.models import User
from app.schemas import RatingIn, RatingListOut, RatingOut, RatingSummaryOut

router = APIRouter()


@router.get("/ratings/summary", response_model=RatingListOut, summary="批量评分聚合（画廊热度，免登录）")
async def list_rating_summaries(
    trip_ids: str = Query(..., description="逗号分隔的行程 id 列表，最多 50 个"),
    db: AsyncSession = Depends(get_session),
) -> RatingListOut:
    """批量返回 count / avg / visited_count（无评分行程返回 count=0, avg=None）。"""
    from app.services import rating_service

    ids = [t.strip() for t in trip_ids.split(",") if t.strip()][:50]
    items = await rating_service.rating_summary(db, ids)
    return RatingListOut(
        items=[RatingSummaryOut(**i) for i in items],
        total=len(items),
    )


@router.get("/{trip_id}/rating", response_model=dict, summary="单行程评分详情（聚合 + 我的评分）")
async def get_trip_rating(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
) -> dict:
    """聚合（count/avg/visited_count）+ 当前登录用户自己的评分（未登录为 None）。"""
    from app.services import rating_service

    return await rating_service.get_rating(db, trip_id, user)


@router.post("/{trip_id}/rating", response_model=RatingOut, status_code=status.HTTP_201_CREATED,
             summary="提交评分（登录，1-5 星 + 我去过标记）")
async def add_trip_rating(
    trip_id: str,
    payload: RatingIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RatingOut:
    """首次评分；重复提交视为改分（幂等 upsert）。"""
    from app.services import rating_service

    rec = await rating_service.upsert_rating(
        db, trip_id, user, rating=payload.rating, visited=payload.visited,
    )
    return RatingOut.model_validate(rec)


@router.put("/{trip_id}/rating", response_model=RatingOut, summary="更新我的评分（幂等）")
async def update_trip_rating(
    trip_id: str,
    payload: RatingIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RatingOut:
    """改分 / 翻转「我去过」；无评分时等价于首次提交。"""
    from app.services import rating_service

    rec = await rating_service.upsert_rating(
        db, trip_id, user, rating=payload.rating, visited=payload.visited,
    )
    return RatingOut.model_validate(rec)


@router.delete("/{trip_id}/rating", status_code=status.HTTP_204_NO_CONTENT,
               summary="删除我的评分（幂等）")
async def delete_trip_rating(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """仅删除自己的评分；未评分则 no-op。"""
    from app.services import rating_service

    await rating_service.delete_rating(db, trip_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)