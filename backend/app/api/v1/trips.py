"""行程 CRUD + 日程/站点管理（支持 owner 用户隔离）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import DayIn, DayOut, ReviseOut, ReviseRequest, ShareOut, StopIn, StopOrderIn, StopOut, StopUpdate, TripCreate, TripListOut, TripOut, TripUpdate
from app.services import budget_service, trip_service

router = APIRouter()


@router.get("/share/{token}", response_model=TripOut, summary="按分享令牌只读查看行程（免登录）")
async def get_shared_trip(
    token: str,
    db: AsyncSession = Depends(get_session),
) -> TripOut:
    """持分享令牌即可免登录查看行程（只读语义，无写接口）。"""
    return await trip_service.get_trip_by_share_token(db, token)


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