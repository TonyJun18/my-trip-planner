"""收藏地点 API（task-social-favorites-flow-eval：collect-first 底座）。

与导入通道的关系（Plotline collect-first 范式落地）：
- 导入（social/note/email/link/screenshot）目前全部是 trip-first（候选并入
  已存在的行程）；本模块补「收集」出口：候选 → 收藏地点（用户自己的收集箱）。
- 行程确定后，收集箱地点可聚合 → 一键成路线（与 favorites-to-route 的
  「收藏行程 → 一键成路线」衔接，两段拼成完整 collect-first 链路）。
- 零凭证、纯规则；外部内容只作为结构化字段（schema 白名单），绝不当指令。

端点：
- POST /favorite-spots/batch  —— 批量收藏导入候选
- GET  /favorite-spots       —— 我的收藏地点（倒序）
- DELETE /favorite-spots/{spot_id} —— 删除一条
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.favorite_spots import (
    FavoriteSpotBatchIn,
    FavoriteSpotBatchOut,
    FavoriteSpotListOut,
)
from app.services import favorite_spots_service as svc

router = APIRouter()


@router.post(
    "/favorite-spots/batch",
    response_model=FavoriteSpotBatchOut,
    summary="批量收藏导入候选地点（collect-first：先攒着，行程确定后再转）",
)
async def collect_spot_batch(
    data: FavoriteSpotBatchIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FavoriteSpotBatchOut:
    """把导入解析出的候选地点批量收藏到用户收集箱（幂等：重复名跳过）。

    - 登录必需（与行程管理一致）；单批上限 50 由 schema 强制（422 超量）。
    - 外部内容按敌意源处理：只取 schema 白名单字段，source_snippet 仅展示。
    """
    result = await svc.collect_spots(db, user, data.spots)
    return FavoriteSpotBatchOut(**result)


@router.get(
    "/favorite-spots",
    response_model=FavoriteSpotListOut,
    summary="我的收藏地点（收集箱，倒序）",
)
async def list_spot_favorites(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FavoriteSpotListOut:
    """当前用户的收藏地点列表（按收藏时间倒序）。"""
    result = await svc.list_spots(db, user, offset=offset, limit=limit)
    return FavoriteSpotListOut(**result)


@router.delete(
    "/favorite-spots/{spot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除一条收藏地点（幂等）",
)
async def remove_spot_favorite(
    spot_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """删除指定收藏地点（仅本人的；不存在 → 404）。"""
    await svc.remove_spot(db, user, spot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)