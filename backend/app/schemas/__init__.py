"""Pydantic Schemas：请求/响应模型。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# DayIn.date 字段名与 datetime.date 类型同名，模型构建时字段名会遮蔽类型名，
# 使用模块级别别名避免 `date | None` 被解析成 `None | None`。
_Date = date

StopType = Literal["attraction", "food", "hotel"]


# ── Trip ──────────────────────────────────────────────────────
class StopIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stop_type: StopType = "attraction"
    lat: float | None = None
    lng: float | None = None
    description: str | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    estimated_duration_minutes: int | None = Field(default=None, ge=0)


class StopOut(StopIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_index: int
    details: dict | None = None


class DayIn(BaseModel):
    day_number: int = Field(ge=1)
    date: _Date | None = None
    note: str | None = None


class DayOut(DayIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    stops: list[StopOut] = []


class TripCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date
    travelers: int = Field(default=1, ge=1)
    budget: float | None = Field(default=None, ge=0)

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date 不能早于 start_date")
        return v


class TripUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    destination: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    travelers: int | None = Field(default=None, ge=1)
    budget: float | None = Field(default=None, ge=0)
    status: Literal["draft", "planning", "confirmed", "archived"] | None = None


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    destination: str
    start_date: date
    end_date: date
    travelers: int
    budget: float | None
    status: str
    created_at: datetime
    updated_at: datetime
    days: list[DayOut] = []


class TripListOut(BaseModel):
    items: list[TripOut]
    total: int


# ── 行程规划请求（Agent 输入） ────────────────────────────────
class PlanRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date
    travelers: int = Field(default=1, ge=1)
    budget: float | None = Field(default=None, ge=0)
    preferences: list[str] = Field(default_factory=list, description="偏好，如 ['美食', '自然风光', '博物馆']")
    provider: Literal["auto", "openai", "deepseek", "ollama"] = "auto"


# ── 行程修订（方案 B：对话改行程） ─────────────────────────────
class ReviseRequest(BaseModel):
    """用户对已生成行程的自然语言修改请求。"""

    message: str = Field(min_length=2, max_length=500, description="修改意图，如「第三天太赶了，西湖只留半天，晚上想吃楼外楼」")
    provider: Literal["auto", "openai", "deepseek", "ollama"] = "auto"


class ReviseAction(BaseModel):
    """一条结构化行程变更指令（由 AI 生成，编排层代码执行）。"""

    model_config = ConfigDict(extra="ignore")

    op: Literal["replace", "add", "remove", "reorder"]
    """replace=改字段 / add=新增站点 / remove=删除站点 / reorder=调整顺序。"""
    day_number: int = Field(ge=1)
    target: dict = Field(default_factory=dict, description="定位目标：{name} 或 {index}（1-based）")
    fields: dict = Field(default_factory=dict, description="replace 时的新字段 / add 时的站点字段")
    index: int | None = Field(default=None, ge=1, description="add 或 reorder 的目标位置（1-based）")


class ReviseDiff(BaseModel):
    """行程修订 diff：AI 只生成指令，不直接改库。"""

    model_config = ConfigDict(extra="ignore")

    actions: list[ReviseAction] = Field(default_factory=list, min_length=1, max_length=10)
    summary: str = Field(default=None, max_length=300)
    """给用户看的变更摘要（如「已把第三天西湖调整为半天，新增楼外楼晚餐」）。"""


class ReviseOut(BaseModel):
    """修订结果：新行程 + 摘要。"""

    trip_id: str
    summary: str
    plan: dict
    trace: list[AgentTraceStep]
    provider: str | None = None
    model: str | None = None


class AgentTraceStep(BaseModel):
    thought: str
    action: str
    action_input: str
    observation: str


class PlanResponse(BaseModel):
    trip_id: str
    plan: dict  # 与 TripPlan.plan_data 同构的完整行程 JSON
    trace: list[AgentTraceStep]
    provider: str
    model: str | None = None
    status: str


# ── 异步规划任务 ──────────────────────────────────────────────
class PlanTaskOut(BaseModel):
    """规划任务的状态查询响应。"""

    task_id: str
    status: Literal["pending", "running", "completed", "failed"]
    provider: str | None = None
    model: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    trip_id: str | None = None
    error: str | None = None
    trace: list[AgentTraceStep] | None = None
    plan: dict | None = None


# ── Health ────────────────────────────────────────────────────
class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    env: str
    database: str
    database_latency_ms: float | None = None


# ── 认证 ──────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    """注册：邮箱或手机号（至少一个）+ 密码。"""

    email: str | None = Field(default=None, max_length=255, description="邮箱（与手机号至少一个）")
    phone: str | None = Field(default=None, max_length=32, description="手机号（与邮箱至少一个）")
    password: str = Field(min_length=8, max_length=128, description="密码（至少 8 位）")
    display_name: str | None = Field(default=None, max_length=100)


class LoginIn(BaseModel):
    """登录：邮箱或手机号 + 密码。"""

    account: str = Field(min_length=3, max_length=255, description="邮箱或手机号")
    password: str = Field(min_length=1, max_length=128)


class UserMeOut(BaseModel):
    """当前用户信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str | None = None
    phone: str | None = None
    display_name: str | None = None


class TokenOut(BaseModel):
    """登录/注册响应：JWT + 用户信息。"""

    access_token: str
    token_type: str = "bearer"
    user: UserMeOut


class UserCreateOut(UserMeOut):
    """（预留）管理员创建用户响应。"""

