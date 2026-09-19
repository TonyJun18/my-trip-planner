"""行程 CRUD + 日程/站点管理（支持 owner 用户隔离）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import DayIn, DayOut, StopIn, StopOut, TripCreate, TripListOut, TripOut, TripUpdate
from app.services import budget_service, trip_service

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