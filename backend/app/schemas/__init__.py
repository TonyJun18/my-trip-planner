"""Pydantic Schemas：请求/响应模型。

按域拆分到子模块，本文件仅做统一再导出（兼容旧 ``from app.schemas import X``）：
- trip: 行程聚合根（Trip / Day / Stop）
- share: 分享令牌 / 行中快照 / 预算汇总
- events: 行程事件流
- escalation: 人工兜底评审队列
- agent: 规划请求 / 异步任务 / 对话式修订
- auth: 认证
- chat: 对话会话与消息
- plan / plan_b / collab / map_edit / social_import / link_import / note_import /
  email_import：独立契约模块（各自直接 import）
- profile / expense 等由 services 或 api 直接引子模块
"""
from __future__ import annotations

from app.schemas.agent import (
    AgentTraceStep,
    PlanQuestion,
    PlanRequest,
    PlanResponse,
    PlanTaskOut,
    ReviseAction,
    ReviseDiff,
    ReviseOut,
    ReviseRequest,
    critic_fix_to_revise_diff,
)
from app.schemas.auth import GoogleLoginIn, LoginIn, RegisterIn, TokenOut, UserCreateOut, UserMeOut
from app.schemas.chat import (
    ChatMessageListOut,
    ChatMessageOut,
    ChatSendIn,
    ChatSessionCreate,
    ChatSessionListOut,
    ChatSessionOut,
)
from app.schemas.escalation import EscalationListOut, EscalationOut, EscalationQualityOut
from app.schemas.events import TripEventListOut, TripEventOut
from app.schemas.expense import ExpenseBalanceOut, ExpenseIn, ExpenseOut
from app.schemas.favorite import FavoriteListOut, FavoriteOut
from app.schemas.health import HealthOut
from app.schemas.plan_b import PlanBOut, PlanBVariantOut
from app.schemas.share import (
    LiveCheckIn,
    LiveSnapshotOut,
    LiveStopOut,
    ShareOut,
    ShareRevokeIn,
    ShareTokenLifecycleOut,
    ShareTtlIn,
    SharedTripOut,
    TripBudgetOut,
)
from app.schemas.trip import (
    DayIn,
    DayOut,
    StopIn,
    StopOrderIn,
    StopOut,
    StopType,
    StopUpdate,
    TripCreate,
    TripListOut,
    TripOut,
    TripUpdate,
)
from app.schemas.xhs import XhsNoteOut, XhsNoteRequest