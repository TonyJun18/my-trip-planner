"""分享/协作 Schemas：分享令牌、受邀编辑、只读快照、预算汇总。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.trip import TripOut


class ShareOut(BaseModel):
    """行程分享：返回只读浏览令牌（前端拼分享链接）。"""

    trip_id: str
    share_token: str
    share_url: str


# ── 分享令牌生命周期（方案 2：task-share-token-lifecycle） ────────
class ShareTokenLifecycleOut(BaseModel):
    """分享/受邀编辑令牌的生命周期状态（owner 视角，含审计汇总）。

    expires_at 为 null 表示永久；revoked_at 非空表示已吊销。
    legacy=True 表示令牌仍在 trips 旧列、本表无记录（按永久兼容）。
    has_password=True 表示该令牌设有访问密码（task-share-gate-eval）。
    """

    trip_id: str
    kind: str  # share / edit
    token: str
    share_url: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    legacy: bool = False
    has_password: bool = False


class ShareRevokeIn(BaseModel):
    """吊销请求：按 kind 吊销对应令牌（share=只读分享 / edit=受邀编辑）。"""

    kind: Literal["share", "edit"] = "share"


class ShareTtlIn(BaseModel):
    """设置分享令牌有效期：days = 1 / 7 / 30（天），0 = 永久。

    expires_at 由服务端按 now + days 计算；重复设置覆盖旧值（幂等）。
    """

    kind: Literal["share", "edit"] = "share"
    days: Literal[0, 1, 7, 30] = Field(description="有效期天数：0=永久，1/7/30 天")


# ── 分享链接访问密码（task-share-gate-eval：可选密码锁） ────────
class SharePasswordIn(BaseModel):
    """设置/清除分享令牌访问密码。

    - kind: share / edit（与 ShareTtlIn 同语义）
    - password: 非空 = 设置新密码（长度 4-64）；空串 = 清除密码（取消保护）
    """

    kind: Literal["share", "edit"] = "share"
    password: str = Field(default="", max_length=64, description="访问密码（4-64 字符）；空串表示清除密码")


class SharePasswordOut(BaseModel):
    """设置结果（绝不回传密码本身）。"""

    trip_id: str
    kind: str
    has_password: bool


class ShareVerifyIn(BaseModel):
    """访客验证分享令牌密码。"""

    password: str = Field(..., max_length=64, description="访问密码")


class ShareVerifyOut(BaseModel):
    """验证结果 + 短期免验凭证（X-Share-Gate: <token>，默认 12h）。

    ok=True 且返回 gate_token：后续请求带 X-Share-Gate 即免重复输密码。
    """

    ok: bool
    gate_token: str | None = None
    expires_in_seconds: int | None = None


# ── 行中「今日视图」（task-live-today-view：MonkeyTravel live trip 差异化） ──
class LiveStopOut(BaseModel):
    """行中快照里的一个站点（带打卡状态）。"""

    id: str
    name: str
    stop_type: str = "attraction"
    checked: bool = False
    order_index: int = 0
    description: str | None = None
    lat: float | None = None
    lng: float | None = None
    # 时间轴派生时刻（schedule_service 注入，非存储）
    visit_start: str | None = None
    visit_end: str | None = None
    is_transfer: bool = False


class LiveSnapshotOut(BaseModel):
    """行中状态快照：阶段 + 今日站点 + 打卡进度。

    phase: upcoming（未开始）/ live（行中）/ finished（已结束）。
    """

    phase: str
    today: str
    trip_id: str
    day_number: int | None = None
    date: str | None = None
    stops: list[LiveStopOut] = []
    completed: int = 0
    total: int = 0
    # 今日天气卡（task-weather-gate-eval）：行中当日天气摘要；无数据/非 live → None
    weather: dict | None = None


class LiveCheckIn(BaseModel):
    """打卡请求。"""

    checked: bool = True


# ── 分享只读响应：TripOut + 预算汇总（分享页免 token 调 budget API） ──────
class TripBudgetOut(BaseModel):
    """与 budget_service.compute_budget 返回值同构的预算汇总。

    人均分摊字段（task-budget-split）均为可选 + 默认值，保持前向兼容：
    旧客户端不感知新字段，新客户端遇到旧数据（无人均字段）也能优雅降级。
    """

    total_estimated: float
    by_type: dict[str, float] = Field(default_factory=dict)
    daily_average: float | None = None
    currency: str = "CNY"
    # 人均分摊（= 总额 / travelers；travelers 异常时不产出）
    per_person_total: float | None = None
    per_person_by_type: dict[str, float] = Field(default_factory=dict)
    per_person_daily: float | None = None
    estimate_basis: dict | None = None


class SharedTripOut(TripOut):
    """公开分享行程详情：在 TripOut 基础上携带预算汇总，分享页无需再本地求和。

    注意字段名用 budget_summary：TripOut.budget 是「用户设定的预算金额」，
    二者不能同名冲突，且分享页两处都需要。
    """

    budget_summary: TripBudgetOut = Field(default_factory=TripBudgetOut)