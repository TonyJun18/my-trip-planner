"""行程 CRUD + 日程/站点管理（支持 owner 用户隔离）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models import Trip, User
from app.schemas import (
    DayIn,
    DayOut,
    FavoriteListOut,
    FavoriteOut,
    ReviseOut,
    ReviseRequest,
    ShareRevokeIn,
    ShareTokenLifecycleOut,
    ShareTtlIn,
    SharedTripOut,
    ShareOut,
    StopIn,
    StopOrderIn,
    StopOut,
    StopUpdate,
    TripCreate,
    TripListOut,
    TripOut,
    TripUpdate,
)
from app.schemas.collab import (
    CommentIn,
    CommentOut,
    InvitedStopUpdate,
    SharedEditOut,
    VoteIn,
    VoteOut,
)
from app.services import budget_service, collab_service, trip_service
from app.services.collab_service import publish_collab

router = APIRouter()


@router.get("/share/{token}", response_model=SharedTripOut, summary="按分享令牌只读查看行程（免登录，含预算汇总）")
async def get_shared_trip(
    token: str,
    db: AsyncSession = Depends(get_session),
) -> SharedTripOut:
    """持分享令牌即可免登录查看行程（只读语义，无写接口）。

    返回 TripOut + budget 汇总（compute_budget），分享页前端无需本地重复计算。
    """
    trip = await trip_service.get_trip_by_share_token(db, token)
    return SharedTripOut(
        **TripOut.model_validate(trip).model_dump(),
        budget_summary=budget_service.compute_budget(trip),
    )


# ── 分享页协作（评论 / 投票，免登录，凭 share_token） ─────────────
@router.get("/share/{token}/comments", response_model=list[CommentOut], summary="分享页评论列表（免登录）")
async def list_share_comments(
    token: str,
    db: AsyncSession = Depends(get_session),
) -> list[CommentOut]:
    """按分享令牌查看行程评论（时间正序）。"""
    return await collab_service.list_comments(db, token)


@router.post("/share/{token}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED, summary="分享页发表评论（免登录）")
async def create_share_comment(
    token: str,
    data: CommentIn,
    db: AsyncSession = Depends(get_session),
) -> CommentOut:
    """访客凭分享令牌发表评论（昵称可选，内容 ≤500 字）。落库后广播给协作频道。"""
    comment = await collab_service.create_comment(db, token, data)
    # 实时同步：通知所有打开分享页的连接（订阅者自行 re-fetch 权威数据）
    trip = await trip_service.get_trip_by_share_token(db, token)
    publish_collab(trip.id, {
        "type": "comment",
        "comment": CommentOut.model_validate(comment).model_dump(mode="json"),
    })
    return comment


@router.get("/share/{token}/votes", response_model=dict[str, VoteOut], summary="分享页站点投票汇总（免登录）")
async def list_share_votes(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> dict[str, VoteOut]:
    """行程内全部站点的 👍/👎 计数；附带当前访客的选择（同 token 匿名身份）。"""
    voter_key = collab_service._voter_key(token, request.client.host if request.client else None, request.headers.get("user-agent"))
    return await collab_service.list_stop_votes(db, token, voter_key=voter_key)


@router.post("/share/{token}/votes/{stop_id}", response_model=VoteOut, summary="站点投票/翻转（免登录）")
async def cast_share_vote(
    token: str,
    stop_id: str,
    data: VoteIn,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> VoteOut:
    """对行程内站点投 👍(1)/👎(-1)；同一访客可翻转，重复提交幂等。"""
    result = await collab_service.cast_vote(
        db,
        token,
        stop_id,
        data,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return VoteOut(**result)


# ── 受邀编辑（凭 edit_token：免登录可编辑站点受限字段/顺序，owner 可收回） ──
@router.get("/edit/{token}", response_model=SharedTripOut, summary="按受邀编辑令牌查看行程（含预算汇总）")
async def get_editable_trip(
    token: str,
    db: AsyncSession = Depends(get_session),
) -> SharedTripOut:
    """编辑令牌同时授予只读权限：受邀者看到与只读分享相同的行程内容。"""
    trip = await trip_service.get_trip_by_edit_token(db, token)
    return SharedTripOut(
        **TripOut.model_validate(trip).model_dump(),
        budget_summary=budget_service.compute_budget(trip),
    )


@router.patch("/edit/{token}/stops/{stop_id}", response_model=StopOut, summary="受邀者编辑站点受限字段")
async def update_invited_stop(
    token: str,
    stop_id: str,
    data: InvitedStopUpdate,
    db: AsyncSession = Depends(get_session),
) -> StopOut:
    """受邀者（凭 edit_token）更新站点 name/description/checked，其余字段不可改。

    与 owner 的 PATCH /days/{day_id}/stops/{stop_id} 不同：这里的授权来源是
    edit_token（免登录），且字段白名单更窄（协作字段，不经 AI 修订）。
    """
    stop = await collab_service.update_invited_stop(db, token, stop_id, data)
    return StopOut.model_validate(stop)


@router.put("/edit/{token}/days/{day_id}/stops/order", response_model=list[StopOut], summary="受邀者重排整日站点顺序")
async def reorder_invited_stops(
    token: str,
    day_id: str,
    data: StopOrderIn,
    db: AsyncSession = Depends(get_session),
) -> list[StopOut]:
    """受邀者（凭 edit_token）按给定顺序重排该日全部站点（幂等，须给出全部站点 id）。"""
    stops = await collab_service.reorder_invited_stops(db, token, day_id, data.order)
    return [StopOut.model_validate(s) for s in stops]


@router.post("/{trip_id}/share/edit", response_model=SharedEditOut, summary="开放受邀编辑权（生成编辑链接）")
async def create_share_edit(
    trip_id: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SharedEditOut:
    """owner 为行程生成受邀编辑链接（幂等：已生成则复用）。"""
    edit_token = await trip_service.create_edit_token(db, trip_id, owner=user.id)
    base = str(request.base_url).rstrip("/")
    return SharedEditOut(
        trip_id=trip_id,
        edit_token=edit_token,
        edit_url=f"{base}/share/{edit_token}?edit=1",
    )


@router.delete("/{trip_id}/share/edit", status_code=status.HTTP_204_NO_CONTENT, summary="收回受邀编辑权")
async def revoke_share_edit(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """owner 收回受邀编辑权：清空 edit_token，已有编辑链接立即失效（只读分享不受影响）。"""
    await trip_service.revoke_edit_token(db, trip_id, owner=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── 分享令牌生命周期（方案 2：task-share-token-lifecycle） ───────────
@router.get(
    "/{trip_id}/share/lifecycle",
    response_model=list[ShareTokenLifecycleOut],
    summary="分享/受邀编辑令牌生命周期状态（owner 视角，含最近使用审计）",
)
async def get_share_lifecycle(
    trip_id: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ShareTokenLifecycleOut]:
    """owner 查看 share + edit 令牌的过期/吊销/最近使用状态。"""
    from app.services import share_lifecycle

    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    base_url = str(request.base_url).rstrip("/")
    items = await share_lifecycle.get_share_lifecycle(db, trip, base_url=base_url)
    return [ShareTokenLifecycleOut(**item) for item in items]


@router.post(
    "/{trip_id}/share/revoke",
    response_model=ShareTokenLifecycleOut,
    summary="吊销分享/受邀编辑令牌（幂等，已有链接立即失效）",
)
async def revoke_share_token(
    trip_id: str,
    data: ShareRevokeIn,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ShareTokenLifecycleOut:
    """owner 吊销某个令牌（share/edit）。吊销后读取侧立即 403，保留审计记录。"""
    from app.services import share_lifecycle

    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    await share_lifecycle.revoke_token(db, trip, kind=data.kind, owner=user.id)
    # 吊销后返回最新生命周期状态（expires/revoked 已更新）
    base_url = str(request.base_url).rstrip("/")
    item = (await share_lifecycle.get_share_lifecycle(db, trip, base_url=base_url))
    match = next((i for i in item if i["kind"] == data.kind), None)
    if match is None:
        raise NotFoundError("分享链接无效", code="share_token_not_found")
    return ShareTokenLifecycleOut(**match)


@router.post(
    "/{trip_id}/share/ttl",
    response_model=ShareTokenLifecycleOut,
    summary="设置分享/受邀编辑令牌有效期（days=0 永久）",
)
async def set_share_token_ttl(
    trip_id: str,
    data: ShareTtlIn,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ShareTokenLifecycleOut:
    """owner 设置令牌 TTL：1/7/30 天过期，或 0 永久。重复设置覆盖旧值。"""
    from app.services import share_lifecycle

    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    await share_lifecycle.set_token_ttl(db, trip, kind=data.kind, days=data.days, owner=user.id)
    base_url = str(request.base_url).rstrip("/")
    item = (await share_lifecycle.get_share_lifecycle(db, trip, base_url=base_url))
    match = next((i for i in item if i["kind"] == data.kind), None)
    if match is None:
        raise NotFoundError("分享链接无效", code="share_token_not_found")
    return ShareTokenLifecycleOut(**match)


# ── 收藏灵感夹（方案 2：登录用户收藏他人分享的行程） ───────────────
@router.get("/favorites", response_model=FavoriteListOut, summary="我的收藏灵感夹")
async def list_favorites(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FavoriteListOut:
    """当前用户的收藏列表（倒序，含行程摘要 + share_token 便于直接打开分享页）。"""
    from app.services import share_lifecycle

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
    from app.services import share_lifecycle

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
    from app.services import share_lifecycle

    await share_lifecycle.remove_favorite(db, trip_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=TripListOut, summary="行程列表")
async def list_trips(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TripListOut:
    trips, total = await trip_service.list_trips(db, offset=offset, limit=limit, owner=user.id)
    return TripListOut(items=trips, total=total)


@router.post("", response_model=TripOut, status_code=status.HTTP_201_CREATED, summary="创建行程")
async def create_trip(
    data: TripCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TripOut:
    return await trip_service.create_trip(db, data, owner=user.id)


@router.get("/{trip_id}", response_model=TripOut, summary="行程详情")
async def get_trip(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TripOut:
    return await trip_service.get_trip(db, trip_id, owner=user.id)


@router.patch("/{trip_id}", response_model=TripOut, summary="更新行程")
async def update_trip(
    trip_id: str,
    data: TripUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TripOut:
    return await trip_service.update_trip(db, trip_id, data, owner=user.id)


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除行程")
async def delete_trip(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    await trip_service.delete_trip(db, trip_id, owner=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{trip_id}/share", response_model=ShareOut, summary="生成行程分享链接")
async def create_share(
    trip_id: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ShareOut:
    """为行程生成只读分享令牌（幂等：已生成则复用），返回完整分享 URL。"""
    token = await trip_service.create_share_token(db, trip_id, owner=user.id)
    base = str(request.base_url).rstrip("/")
    return ShareOut(trip_id=trip_id, share_token=token, share_url=f"{base}/share/{token}")


@router.post("/{trip_id}/days", response_model=DayOut, status_code=status.HTTP_201_CREATED, summary="添加日程")
async def add_day(
    trip_id: str,
    data: DayIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> DayOut:
    return await trip_service.add_day(db, trip_id, data, owner=user.id)


@router.post("/{trip_id}/days/generate", response_model=list[DayOut], summary="按日期范围批量生成日程")
async def generate_days(
    trip_id: str,
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[DayOut]:
    from datetime import date

    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    days = await trip_service.generate_days_for_range(db, trip_id, start_d, end_d, owner=user.id)
    return days


@router.post("/days/{day_id}/stops", response_model=StopOut, status_code=status.HTTP_201_CREATED, summary="添加站点")
async def add_stop(
    day_id: str,
    data: StopIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StopOut:
    return await trip_service.add_stop(db, day_id, data, owner=user.id)


@router.patch("/days/{day_id}/stops/{stop_id}", response_model=StopOut, summary="编辑站点（手动细粒度编辑）")
async def update_stop(
    day_id: str,
    stop_id: str,
    data: StopUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StopOut:
    """手动编辑单个站点字段：仅更新传入字段，其余保持原值（与 AI 修订并存）。"""
    return await trip_service.update_stop(db, day_id, stop_id, data, owner=user.id)


@router.put("/days/{day_id}/stops/order", response_model=list[StopOut], summary="重排整日站点顺序")
async def reorder_stops(
    day_id: str,
    data: StopOrderIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[StopOut]:
    """按给定顺序重排该日全部站点（用于前端上移/下移/拖拽）。"""
    return await trip_service.reorder_stops(db, day_id, data.order, owner=user.id)


@router.delete("/days/{day_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除日程（级联站点）")
async def delete_day(
    day_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    await trip_service.delete_day(db, day_id, owner=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/days/{day_id}/stops/{stop_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除站点")
async def delete_stop(
    day_id: str,
    stop_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    await trip_service.delete_stop(db, stop_id, owner=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{trip_id}/budget", summary="行程预算明细")
async def get_budget(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    return budget_service.compute_budget(trip)


@router.get("/{trip_id}/plan", summary="行程完整方案（Agent 输出快照）")
async def get_trip_plan(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """返回 TripPlan.plan_data（含 days/budget/hotels 候选列表）。

    用于前端展示 Agent 规划时的「酒店推荐」等 plan 级信息；
    详情页的主数据仍来自 GET /trips/{id}。
    """
    plan = await trip_service.get_plan(db, trip_id, owner=user.id)
    if plan is None:
        raise NotFoundError("该行程还没有 AI 规划方案", code="trip_plan_not_found")
    return plan.plan_data


@router.post("/{trip_id}/revise", response_model=ReviseOut, summary="对话式修订行程（AI 生成 diff，代码执行）")
async def revise_trip(
    trip_id: str,
    data: ReviseRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ReviseOut:
    """把用户对行程的自然语言修改请求转成结构化变更并原子应用。"""
    from app.services import revise_service

    result = await revise_service.revise_trip(
        db,
        trip_id,
        data.message,
        owner=user.id,
        provider=data.provider,
    )
    return ReviseOut(**result)