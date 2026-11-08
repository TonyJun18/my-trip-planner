"""Trips 分享域路由：只读分享 / 受邀编辑 / 令牌生命周期。

顺序说明：本 router 在 ``trips.py`` 聚合聚合时**最先**注册——
``/share/{token}``、``/edit/{token}`` 是字面量第一段，必须先于
``/{trip_id}`` 动态路由匹配，避免 ``trip_id="share"`` 被吞。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models import User
from app.schemas import (
    LiveCheckIn,
    LiveSnapshotOut,
    ShareOut,
    SharePasswordIn,
    SharePasswordOut,
    ShareRevokeIn,
    ShareTokenLifecycleOut,
    ShareTtlIn,
    ShareVerifyIn,
    ShareVerifyOut,
    SharedTripOut,
    StopOrderIn,
    StopOut,
    TripBudgetOut,
    TripEventListOut,
    TripEventOut,
    TripOut,
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
    x_share_password: str | None = Header(None, alias="X-Share-Password", description="分享令牌访问密码（可选）"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate", description="已签发的免验凭证（可选）"),
    db: AsyncSession = Depends(get_session),
) -> SharedTripOut:
    """持分享令牌即可免登录查看行程（只读语义，无写接口）。

    返回 TripOut + budget 汇总（compute_budget），分享页前端无需本地重复计算。
    """
    trip = await trip_service.get_trip_by_share_token(db, token, password=x_share_password, gate_token=x_share_gate)
    # 分享 token 已校验访问权：直接按 trip_id 查 plan（不做 owner 过滤）
    plan = await trip_service.get_plan_by_trip_id(db, trip.id)
    plan_data = await trip_service.ensure_plan_transport(db, trip, plan)
    return SharedTripOut(
        **TripOut.model_validate(trip).model_dump(),
        budget_summary=TripBudgetOut.model_validate(
            budget_service.compute_budget(trip, plan_data=plan_data)
        ),
    )


# ── 行中「今日视图」只读版（share_token 免登录查看；无写接口） ──
@router.get("/share/{token}/live", response_model=LiveSnapshotOut, summary="行中「今日视图」快照（免登录只读，凭 share_token）")
async def get_live_snapshot_shared(
    token: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> LiveSnapshotOut:
    """持只读分享令牌即可查看行中快照（不开放打卡/顺延等写操作）。

    与受邀编辑版（/edit/{token}/live）的差异：分享令牌只有读权限，
    行中只读卡片用于同伴围观进度，避免误操作。
    """
    from app.services import live_service

    trip = await trip_service.get_trip_by_share_token(db, token, password=x_share_password, gate_token=x_share_gate)
    return LiveSnapshotOut(**live_service.live_snapshot(trip))


# ── 分享页协作（评论 / 投票，免登录，凭 share_token） ─────────────
@router.get("/share/{token}/comments", response_model=list[CommentOut], summary="分享页评论列表（免登录）")
async def list_share_comments(
    token: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> list[CommentOut]:
    """按分享令牌查看行程评论（时间正序）。"""
    return await collab_service.list_comments(db, token, password=x_share_password, gate_token=x_share_gate)


@router.post("/share/{token}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED, summary="分享页发表评论（免登录）")
async def create_share_comment(
    token: str,
    data: CommentIn,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> CommentOut:
    """访客凭分享令牌发表评论（昵称可选，内容 ≤500 字）。落库后广播给协作频道。"""
    comment = await collab_service.create_comment(db, token, data, password=x_share_password, gate_token=x_share_gate)
    # 实时同步：通知所有打开分享页的连接（订阅者自行 re-fetch 权威数据）
    trip = await trip_service.get_trip_by_share_token(db, token, password=x_share_password, gate_token=x_share_gate)
    publish_collab(trip.id, {
        "type": "comment",
        "comment": CommentOut.model_validate(comment).model_dump(mode="json"),
    })
    return comment


@router.get("/share/{token}/votes", response_model=dict[str, VoteOut], summary="分享页站点投票汇总（免登录）")
async def list_share_votes(
    token: str,
    request: Request,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, VoteOut]:
    """行程内全部站点的 👍/👎 计数；附带当前访客的选择（同 token 匿名身份）。"""
    voter_key = collab_service._voter_key(token, request.client.host if request.client else None, request.headers.get("user-agent"))
    return await collab_service.list_stop_votes(db, token, voter_key=voter_key, password=x_share_password, gate_token=x_share_gate)


@router.post("/share/{token}/votes/{stop_id}", response_model=VoteOut, summary="站点投票/翻转（免登录）")
async def cast_share_vote(
    token: str,
    stop_id: str,
    data: VoteIn,
    request: Request,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
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
        password=x_share_password,
        gate_token=x_share_gate,
    )
    return VoteOut(**result)


# ── 受邀编辑（凭 edit_token：免登录可编辑站点受限字段/顺序，owner 可收回） ──
@router.get("/edit/{token}", response_model=SharedTripOut, summary="按受邀编辑令牌查看行程（含预算汇总）")
async def get_editable_trip(
    token: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> SharedTripOut:
    """编辑令牌同时授予只读权限：受邀者看到与只读分享相同的行程内容。"""
    trip = await trip_service.get_trip_by_edit_token(db, token, password=x_share_password, gate_token=x_share_gate)
    # 编辑 token 已校验访问权：直接按 trip_id 查 plan（不做 owner 过滤）
    plan = await trip_service.get_plan_by_trip_id(db, trip.id)
    plan_data = await trip_service.ensure_plan_transport(db, trip, plan)
    return SharedTripOut(
        **TripOut.model_validate(trip).model_dump(),
        budget_summary=TripBudgetOut.model_validate(
            budget_service.compute_budget(trip, plan_data=plan_data)
        ),
    )


@router.patch("/edit/{token}/stops/{stop_id}", response_model=StopOut, summary="受邀者编辑站点受限字段")
async def update_invited_stop(
    token: str,
    stop_id: str,
    data: InvitedStopUpdate,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> StopOut:
    """受邀者（凭 edit_token）更新站点 name/description/checked，其余字段不可改。

    与 owner 的 PATCH /days/{day_id}/stops/{stop_id} 不同：这里的授权来源是
    edit_token（免登录），且字段白名单更窄（协作字段，不经 AI 修订）。
    """
    stop = await collab_service.update_invited_stop(db, token, stop_id, data, password=x_share_password, gate_token=x_share_gate)
    return StopOut.model_validate(stop)


@router.put("/edit/{token}/days/{day_id}/stops/order", response_model=list[StopOut], summary="受邀者重排整日站点顺序")
async def reorder_invited_stops(
    token: str,
    day_id: str,
    data: StopOrderIn,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> list[StopOut]:
    """受邀者（凭 edit_token）按给定顺序重排该日全部站点（幂等，须给出全部站点 id）。"""
    stops = await collab_service.reorder_invited_stops(db, token, day_id, data.order, password=x_share_password, gate_token=x_share_gate)
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


@router.post("/{trip_id}/share/password", response_model=SharePasswordOut, summary="设置/清除分享或受邀编辑令牌访问密码（owner）")
async def set_share_password(
    trip_id: str,
    data: SharePasswordIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SharePasswordOut:
    """owner 设置/清除令牌访问密码。

    - password 非空 → 设置/覆盖密码（PBKDF2 哈希落库，与登录密码同格式）
    - password 空串 → 清除密码（取消保护，幂等）
    - 密码本身绝不回传；只透出 has_password 布尔
    """
    from app.services import share_lifecycle

    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    result = await share_lifecycle.set_token_password(
        db, trip, kind=data.kind, password=data.password, owner=user.id
    )
    return SharePasswordOut(**result)


@router.post("/share/{token}/verify", response_model=ShareVerifyOut, summary="访客验证分享令牌访问密码（成功后签发短期免验凭证）")
async def verify_share_password(
    token: str,
    data: ShareVerifyIn,
    db: AsyncSession = Depends(get_session),
) -> ShareVerifyOut:
    """验证分享令牌密码 → 签发 X-Share-Gate 免验凭证（默认 12h）。

    - 密码错误 → 403 share_password_required（与读取侧同语义）
    - 验证通过 → gate_token（HMAC 签名，含 token/kind/过期时间戳），
      后续请求带 X-Share-Gate header 免重复输密码
    """
    from app.services import share_lifecycle

    # 完整门禁（生命周期 + 密码）与读取侧同一条路径；密码错误在此抛 403
    await trip_service.get_trip_by_share_token(db, token, password=data.password)
    return ShareVerifyOut(
        ok=True,
        gate_token=share_lifecycle.issue_gate_token(token, "share"),
        expires_in_seconds=share_lifecycle.GATE_TTL_SECONDS,
    )


@router.post("/edit/{token}/verify", response_model=ShareVerifyOut, summary="受邀编辑链接验证访问密码（成功后签发免验凭证）")
async def verify_edit_password(
    token: str,
    data: ShareVerifyIn,
    db: AsyncSession = Depends(get_session),
) -> ShareVerifyOut:
    """受邀编辑令牌的密码验证 → 签发 kind='edit' 的 X-Share-Gate 免验凭证（默认 12h）。

    补齐 share-gate 的编辑侧闭环：owner 可给 kind='edit' 单独设密码（
    POST /{trip_id}/share/password），但读取侧（/trips/edit/{token} 全链路、
    行中、拖拽编辑）都会 403——此前只有 share 侧的 verify 端点，受邀者拿到
    加密编辑链接后无处解锁。语义与 share 侧完全一致：密码错误 → 403
    share_password_required；通过 → gate_token（HMAC，绑定 token + kind=edit）。
    """
    from app.services import share_lifecycle

    await trip_service.get_trip_by_edit_token(db, token, password=data.password)
    return ShareVerifyOut(
        ok=True,
        gate_token=share_lifecycle.issue_gate_token(token, "edit"),
        expires_in_seconds=share_lifecycle.GATE_TTL_SECONDS,
    )


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


# ── 行程事件流（免登录双路径，凭 share/edit token） ────────────────
@router.get("/share/{token}/events", response_model=TripEventListOut, summary="行程事件流（免登录，凭 share_token 只读）")
async def list_shared_trip_events(
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> TripEventListOut:
    """分享页查看事件流（只读语义，凭 share_token 免登录）。"""
    from app.services import event_service

    trip = await trip_service.get_trip_by_share_token(db, token, password=x_share_password, gate_token=x_share_gate)
    events = await event_service.list_events(db, trip.id, limit=limit, offset=offset)
    return TripEventListOut(
        items=[TripEventOut(**event_service.event_out(e)) for e in events],
        total=len(events),
    )


# ── 分享页旅程追踪（免登录只读，脱敏：不含费用/凭证） ─────────────
@router.get("/share/{token}/journey", response_model=dict, summary="分享页旅程追踪（免登录只读，脱敏）")
async def get_shared_trip_journey(
    token: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """凭 share_token 免登录查看旅程追踪（脱敏版：只有打卡进度/按天状态/高光/预订计数，
    不含费用与凭证——财务数据只对 owner 与受邀编辑者开放，与费用 API 同信任语义）。"""
    from app.services import journey_service

    trip = await trip_service.get_trip_by_share_token(db, token, password=x_share_password, gate_token=x_share_gate)
    return await journey_service.journey_projection_shared(db, trip)


@router.get("/edit/{token}/events", response_model=TripEventListOut, summary="行程事件流（免登录，凭 edit_token）")
async def list_editable_trip_events(
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> TripEventListOut:
    """受邀编辑者查看事件流（凭 edit_token 免登录）。"""
    from app.services import event_service

    trip = await trip_service.get_trip_by_edit_token(db, token, password=x_share_password, gate_token=x_share_gate)
    events = await event_service.list_events(db, trip.id, limit=limit, offset=offset)
    return TripEventListOut(
        items=[TripEventOut(**event_service.event_out(e)) for e in events],
        total=len(events),
    )


# ── 行中「今日视图」受邀编辑版（免登录，凭 edit_token；ShareView 同伴操作） ──
@router.get("/edit/{token}/live", response_model=LiveSnapshotOut, summary="行中「今日视图」快照（免登录，凭 edit_token）")
async def get_live_snapshot_by_token(
    token: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> LiveSnapshotOut:
    """受邀者（持 edit_token）免登录查看行中快照（投稿 → 实时同伴操作）。"""
    from app.services import live_service

    trip = await trip_service.get_trip_by_edit_token(db, token, password=x_share_password, gate_token=x_share_gate)
    return LiveSnapshotOut(**live_service.live_snapshot(trip))


@router.post("/edit/{token}/live/stops/{stop_id}/check", response_model=LiveSnapshotOut, summary="打卡/取消打卡（免登录，凭 edit_token）")
async def check_live_stop_by_token(
    token: str,
    stop_id: str,
    data: LiveCheckIn | None = None,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> LiveSnapshotOut:
    """受邀者免登录打卡/取消（与受邀编辑站点同信任语义）。"""
    from app.services import live_service

    checked = data.checked if data else True
    result = await live_service.check_stop_by_token(db, token, stop_id, checked=checked, password=x_share_password, gate_token=x_share_gate)
    return LiveSnapshotOut(**result["live"])


@router.post("/edit/{token}/live/stops/{stop_id}/skip", response_model=LiveSnapshotOut, summary="跳过今日站点（免登录，凭 edit_token）")
async def skip_live_stop_by_token(
    token: str,
    stop_id: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> LiveSnapshotOut:
    """受邀者免登录跳过今日站点。"""
    from app.services import live_service

    result = await live_service.skip_stop_by_token(db, token, stop_id, password=x_share_password, gate_token=x_share_gate)
    return LiveSnapshotOut(**result["live"])


@router.post("/edit/{token}/live/delay", response_model=LiveSnapshotOut, summary="迟到一键顺延（免登录，凭 edit_token）")
async def delay_live_trip_by_token(
    token: str,
    x_share_password: str | None = Header(None, alias="X-Share-Password"),
    x_share_gate: str | None = Header(None, alias="X-Share-Gate"),
    db: AsyncSession = Depends(get_session),
) -> LiveSnapshotOut:
    """受邀者免登录迟到顺延（所有日期 +1 天）。"""
    from app.services import live_service

    result = await live_service.delay_today_by_token(db, token)
    return LiveSnapshotOut(**result["live"])