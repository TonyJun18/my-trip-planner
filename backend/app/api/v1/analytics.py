"""前端意图埋点端点（task-trip-detail-refactor：基线事件，不落库）。

设计决策（对齐 docs/prd/2026-10-29-trip-detail-refactor-spec.md §3）：
- fire-and-forget：入参白名单校验通过即返回 204，不落库不查库，尽力而为
- 不强制登录：guest 角色（share 页）也允许上报，role 由前端透传
- 每次请求最多写一行结构化日志（LOG_FORMAT=json 时带 trace_id），
  回看基线时可按日志聚合，也可以在需要时再落库，改造成本为零
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.analytics import AnalyticsEvent
from app.schemas.analytics import AnalyticsEventIn

logger = logging.getLogger(__name__)

router = APIRouter()

# 事件名 → 中文说明（日志可读性）
_EVENT_LABELS = {
    "planning_tool_open": "规划工具打开",
    "top_action_click": "顶栏主操作",
    "itinerary_first_view": "逐日行程首屏可见",
    "itinerary_scroll_depth": "滚动深度",
    "workspace_tab_switch": "工作台 tab 切换",
    "workspace_all_toggle": "全部工具开关",
}


@router.post(
    "/events",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="前端意图埋点（匿名遥测，不落库）",
)
async def record_event(
    data: AnalyticsEventIn,
    db: AsyncSession = Depends(get_session),
) -> Response:
    """记录一条意图/曝光事件。

    - 意图埋点（缺省）：白名单校验失败由 pydantic 返回 422；只写日志不落库
    - 漏斗埋点（``dedicated: true``）：校验 5 类白名单后落 ``analytics_events``
    - 落库失败只记日志，仍返回 204（调用方 fire-and-forget，不影响业务）
    """
    if data.dedicated:
        if data.funnel is None:
            raise HTTPException(status_code=422, detail="dedicated 事件缺少 funnel")
        event = AnalyticsEvent(
            event_name=data.funnel.name,
            user_id=data.funnel.user_id,
            trip_id=data.funnel.trip_id,
            anonymous_session_id=data.funnel.anonymous_session_id,
            payload=data.funnel.payload or {},
        )
        try:
            # 独立事务落库（与请求事务解耦）；无工厂时退回请求会话
            factory = getattr(db, "session_factory", None)
            if factory is not None:
                async with factory() as session:
                    session.add(event)
                    await session.commit()
            else:
                db.add(event)
                await db.flush()
        except Exception:  # noqa: BLE001 - 埋点失败绝不阻断业务
            logger.exception("analytics_funnel_persist_failed name=%s", data.funnel.name)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if data.name is None:
        raise HTTPException(status_code=422, detail="name 不能为空")
    p = data.payload
    logger.info(
        "analytics_event name=%s label=%s trip_id=%s phase=%s viewport=%s touch=%s role=%s "
        "tool=%s action=%s visible=%s depth=%s tab=%s from=%s on=%s",
        data.name,
        _EVENT_LABELS.get(data.name, ""),
        p.trip_id,
        p.trip_phase,
        p.viewport_width,
        p.is_touch,
        p.role,
        p.tool,
        p.action,
        p.visible,
        p.depth,
        p.tab,
        p.from_tab,
        p.on,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)