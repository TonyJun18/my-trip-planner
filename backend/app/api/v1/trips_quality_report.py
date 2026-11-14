"""质检报告 API（task-trip-quality-report-a/b）。

端点（双路径，与 export_service 同信任语义）：
- GET /trips/{trip_id}/quality-report         —— owner（JWT）
- GET /trips/share/{token}/quality-report     —— 分享令牌免登录只读
  （share 路径多一段字面量 /share/，Starlette 精确段匹配不吞并；
   本 router 注册在 trips_share 之后、trips_crud 之前，见 api/v1/__init__.py）

只读纯函数：从 TripPlan.plan_data 聚合五类质检（quality / time_gate /
repeat_gate / weather_gate / dynamic_facts），零 LLM、零写库、零凭证输出。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.schemas import QualityReportOut
from app.services import quality_report_service, trip_service

router = APIRouter()


async def _report_for_plan(plan_data: dict | None) -> QualityReportOut:
    """构建响应（双路径共用：owner 的 plan_data 与 share 的 plan_data 同构）。"""
    report = quality_report_service.build_quality_report(plan_data)
    return QualityReportOut.model_validate(report)


@router.get(
    "/{trip_id}/quality-report",
    response_model=QualityReportOut,
    summary="行程质检报告（owner，五类只读聚合）",
)
async def get_trip_quality_report(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> QualityReportOut:
    """owner 查看行程质检报告。"""
    plan = await trip_service.get_plan(db, trip_id, owner=user.id)
    return await _report_for_plan(plan.plan_data if plan else None)


@router.get(
    "/share/{token}/quality-report",
    response_model=QualityReportOut,
    summary="行程质检报告（分享令牌免登录只读）",
)
async def get_shared_trip_quality_report(
    token: str,
    x_share_password: str | None = None,
    x_share_gate: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> QualityReportOut:
    """分享令牌免登录查看质检报告（只读；不含任何凭证/订单字段）。"""
    trip = await trip_service.get_trip_by_share_token(
        db, token,
        password=x_share_password,
        gate_token=x_share_gate,
    )
    plan = await trip_service.get_plan_by_trip_id(db, trip.id)
    return await _report_for_plan(plan.plan_data if plan else None)