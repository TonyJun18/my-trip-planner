"""Trips 主域路由：CRUD / 日程站点 / 预算 / 方案 / 修订 / 行中 / 事件流 / 小红书。

注册顺序约束（在 ``__init__.py`` 聚合时体现）：
- 本 router 在 ``trips_escalations`` / ``trips_gallery`` / ``trips_share`` 之后注册——
  ``/escalations``、``/gallery``、``/share``、``/edit`` 字面量段优先匹配。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.i18n import normalize_locale
from app.models import User
from app.schemas import (
    DayIn,
    DayOut,
    LiveCheckIn,
    LiveSnapshotOut,
    ReviseOut,
    ReviseRequest,
    StopIn,
    StopOrderIn,
    StopOut,
    StopUpdate,
    TripCreate,
    TripEventListOut,
    TripEventOut,
    TripListOut,
    TripOut,
    TripUpdate,
    XhsNoteOut,
    XhsNoteRequest,
)
from app.services import budget_service, trip_service, xhs_service

router = APIRouter()


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
    trip = await trip_service.create_trip(db, data, owner=user.id)
    return TripOut.model_validate(trip)


@router.get("/{trip_id}", response_model=TripOut, summary="行程详情")
async def get_trip(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TripOut:
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    return TripOut.model_validate(trip)


# ── 小红书笔记（方案 A：内容工厂，用户复制后在 App 内发布） ──────
@router.post("/{trip_id}/xhs-note", response_model=XhsNoteOut, summary="生成小红书笔记文案（AI 生成 + 规则兜底）")
async def generate_xhs_note(
    trip_id: str,
    data: XhsNoteRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> XhsNoteOut:
    """为行程生成适配小红书发布的笔记（标题/正文/话题）。

    - LLM 主路径：按小红书种草文风格生成；失败自动降级为规则模板（绝不无声失败）
    - 返回 source 字段标注 llm / template，供前端提示「AI 生成」或「模板生成」
    - 发布仍由用户完成（复制 → 小红书 App 粘贴），接口不含自动发布副作用
    """
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    note, source = await xhs_service.generate_xhs_note(trip, provider=data.provider)
    spec = xhs_service.note_image_spec()
    return XhsNoteOut(
        title=note.title,
        body=note.body,
        topics=note.topics,
        full_text=note.full_text,
        source=source,
        image_spec={"width": spec.width, "height": spec.height, "ratio": spec.ratio},
    )


@router.patch("/{trip_id}", response_model=TripOut, summary="更新行程")
async def update_trip(
    trip_id: str,
    data: TripUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TripOut:
    trip = await trip_service.update_trip(db, trip_id, data, owner=user.id)
    return TripOut.model_validate(trip)


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除行程")
async def delete_trip(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    await trip_service.delete_trip(db, trip_id, owner=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{trip_id}/days", response_model=DayOut, status_code=status.HTTP_201_CREATED, summary="添加日程")
async def add_day(
    trip_id: str,
    data: DayIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> DayOut:
    day = await trip_service.add_day(db, trip_id, data, owner=user.id)
    return DayOut.model_validate(day)


@router.post("/{trip_id}/days/generate", response_model=list[DayOut], summary="按日期范围批量生成日程")
async def generate_days(
    trip_id: str,
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[DayOut]:
    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    days = await trip_service.generate_days_for_range(db, trip_id, start_d, end_d, owner=user.id)
    return [DayOut.model_validate(d) for d in days]


@router.post("/days/{day_id}/stops", response_model=StopOut, status_code=status.HTTP_201_CREATED, summary="添加站点")
async def add_stop(
    day_id: str,
    data: StopIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StopOut:
    stop = await trip_service.add_stop(db, day_id, data, owner=user.id)
    return StopOut.model_validate(stop)


@router.patch("/days/{day_id}/stops/{stop_id}", response_model=StopOut, summary="编辑站点（手动细粒度编辑）")
async def update_stop(
    day_id: str,
    stop_id: str,
    data: StopUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StopOut:
    """手动编辑单个站点字段：仅更新传入字段，其余保持原值（与 AI 修订并存）。"""
    stop = await trip_service.update_stop(db, day_id, stop_id, data, owner=user.id)
    return StopOut.model_validate(stop)


@router.put("/days/{day_id}/stops/order", response_model=list[StopOut], summary="重排整日站点顺序")
async def reorder_stops(
    day_id: str,
    data: StopOrderIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[StopOut]:
    """按给定顺序重排该日全部站点（用于前端上移/下移/拖拽）。"""
    stops = await trip_service.reorder_stops(db, day_id, data.order, owner=user.id)
    return [StopOut.model_validate(s) for s in stops]


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
    plan = await trip_service.get_plan(db, trip_id, owner=user.id)
    plan_data = await trip_service.ensure_plan_transport(db, trip, plan)
    return budget_service.compute_budget(trip, plan_data=plan_data)


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
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    return await trip_service.ensure_plan_transport(db, trip, plan)


@router.post("/{trip_id}/revise", response_model=ReviseOut, summary="对话式修订行程（AI 生成 diff，代码执行）")
async def revise_trip(
    trip_id: str,
    data: ReviseRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ReviseOut:
    """把用户对行程的自然语言修改请求转成结构化变更并原子应用。

    语言契约（与 /planner/plan 一致）：显式 ``language`` 优先，
    未传时按 ``Accept-Language`` 头解析；修订 diff summary / 质检报告
    按此语种输出。
    """
    from app.services import revise_service

    if not data.language:
        data.language = normalize_locale(request.headers.get("accept-language"))
    result = await revise_service.revise_trip(
        db,
        trip_id,
        data.message,
        owner=user.id,
        provider=data.provider,
        language=data.language,
        max_review_rounds=2,
    )
    return ReviseOut(**result)


# ── 行中「今日视图」（task-live-today-view：MonkeyTravel live trip 差异化） ──
# 行程日期已开始时的现场陪伴：今日快照 / 打卡 / 跳过 / 迟到一键顺延 / 替代候选。
# 全部为确定性操作（不经过 LLM），复用 revise 原子内核 + DrivingGate 约束 +
# collab WS feed 事件广播（同伴免登录实时可见）。
@router.get("/{trip_id}/live", response_model=LiveSnapshotOut, summary="行中「今日视图」快照（归一化阶段 + 今日站点 + 打卡进度）")
async def get_live_snapshot(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> LiveSnapshotOut:
    """行中状态只读快照：upcoming / live / finished 三态 + 今日站点列表。"""
    from app.services import live_service

    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    return LiveSnapshotOut(**live_service.live_snapshot(trip))


@router.post("/{trip_id}/live/stops/{stop_id}/check", response_model=LiveSnapshotOut, summary="打卡/取消打卡（行中）")
async def check_live_stop(
    trip_id: str,
    stop_id: str,
    data: LiveCheckIn | None = None,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> LiveSnapshotOut:
    """标记今日站点完成（checked=True）或取消（checked=False），返回最新行中快照。"""
    from app.services import live_service

    checked = data.checked if data else True
    result = await live_service.check_stop(db, trip_id, stop_id, checked=checked, owner=user.id)
    return LiveSnapshotOut(**result["live"])


@router.post("/{trip_id}/live/stops/{stop_id}/skip", response_model=LiveSnapshotOut, summary="跳过今日站点（行中）")
async def skip_live_stop(
    trip_id: str,
    stop_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> LiveSnapshotOut:
    """跳过今日某站点（删除），返回最新行中快照。"""
    from app.services import live_service

    result = await live_service.skip_stop(db, trip_id, stop_id, owner=user.id)
    return LiveSnapshotOut(**result["live"])


@router.post("/{trip_id}/live/delay", response_model=LiveSnapshotOut, summary="迟到一键顺延（今日及之后整体后移一天，行中）")
async def delay_live_trip(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> LiveSnapshotOut:
    """迟到一键顺延：所有日期 +1 天（行程不缩水），今日未完成站点自然落到明天。"""
    from app.services import live_service

    result = await live_service.delay_today(db, trip_id, owner=user.id)
    return LiveSnapshotOut(**result["live"])


# ── 行程事件流（task-trip-event-notify：主动通知最小版） ─────────────
# 修订/打卡/跳过/顺延/评论/投票等业务动作 append-only 记录到 trip_events，
# 事件流是「事实记录」不做状态承载；owner（JWT）与受邀者（share/edit token）
# 均可在自己的权限范围内读取事件（免登录双路径与 live 快照同构）。
@router.get("/{trip_id}/events", response_model=TripEventListOut, summary="行程事件流（owner，最新在前，分页）")
async def list_trip_events(
    trip_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TripEventListOut:
    """owner 查看行程事件流（修订/打卡/跳过/顺延/评论/投票）。"""
    from app.services import event_service

    # owner 归属校验（复用 trip_service 的隔离语义）
    await trip_service.get_trip(db, trip_id, owner=user.id)
    events = await event_service.list_events(db, trip_id, limit=limit, offset=offset)
    return TripEventListOut(
        items=[TripEventOut(**event_service.event_out(e)) for e in events],
        total=len(events),
    )