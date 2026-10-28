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
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    estimated_duration_minutes: int | None = Field(default=None, ge=0)


class StopOut(StopIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_index: int
    checked: bool = False
    details: dict | None = None


class StopUpdate(BaseModel):
    """手动编辑站点：所有字段可选，未传字段保持原值。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    stop_type: StopType | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    estimated_duration_minutes: int | None = Field(default=None, ge=0)


class StopOrderIn(BaseModel):
    """整日站点顺序重排：提供该日全部站点 id，按给定顺序写入 order_index。"""

    order: list[str] = Field(min_length=1, description="该日全部站点 id，按目标顺序排列")


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
    departure: str | None = Field(default=None, max_length=200, description="出发地（可选）")
    trip_type: str | None = Field(default=None, max_length=20, description="出行性质：休闲旅游/商务出差/探亲访友/亲子出游/蜜月度假")
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
    departure: str | None = Field(default=None, max_length=200, description="出发地（可选）；传 null 清空")
    trip_type: str | None = Field(default=None, max_length=20, description="出行性质：休闲旅游/商务出差/探亲访友/亲子出游/蜜月度假")
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
    departure: str | None = None
    trip_type: str | None = None
    start_date: date
    end_date: date
    travelers: int
    budget: float | None
    status: str
    share_token: str | None = None
    edit_token: str | None = None
    # 人工兜底（task-human-escalation-eval）：最新 AI plan 的 quality 是否命中
    # 需人工复核信号（finalized / passed=false / degraded）。派生字段，非存储。
    escalated: bool = False
    created_at: datetime
    updated_at: datetime
    days: list[DayOut] = []


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


class ShareRevokeIn(BaseModel):
    """吊销请求：按 kind 吊销对应令牌（share=只读分享 / edit=受邀编辑）。"""

    kind: Literal["share", "edit"] = "share"


class ShareTtlIn(BaseModel):
    """设置分享令牌有效期：days = 1 / 7 / 30（天），0 = 永久。

    expires_at 由服务端按 now + days 计算；重复设置覆盖旧值（幂等）。
    """

    kind: Literal["share", "edit"] = "share"
    days: Literal[0, 1, 7, 30] = Field(description="有效期天数：0=永久，1/7/30 天")


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


class LiveCheckIn(BaseModel):
    """打卡请求。"""

    checked: bool = True


class TripEventOut(BaseModel):
    """行程事件（task-trip-event-notify）：append-only 事件流的单条记录。

    - event_type: revise / check / skip / delay / comment / vote / edit / share
    - payload: 可读摘要（前端 feed 直接展示）
    """

    id: str
    trip_id: str
    event_type: str
    payload: dict | None = None
    created_at: datetime | None = None


class TripEventListOut(BaseModel):
    """行程事件列表（最新在前，分页）。"""

    items: list[TripEventOut] = []
    total: int = 0


class TripListOut(BaseModel):
    items: list[TripOut]
    total: int


# ── 人工兜底评审队列（task-human-escalation-eval） ────────────────
class EscalationQualityOut(BaseModel):
    """结构化失败摘要（从 plan.quality 提炼，供 owner 评审/自托管接人工）。"""

    reason: str | None = None  # finalized / low_confidence / degraded
    summary: str | None = None
    issues: list = Field(default_factory=list)  # 最多 5 条
    score: int | None = None


class EscalationOut(BaseModel):
    """评审队列中的一条（escalated 行程 + 失败摘要）。"""

    trip_id: str
    title: str
    destination: str
    start_date: date
    end_date: date
    budget: float | None = None
    escalated_at: str | None = None
    quality: EscalationQualityOut = Field(default_factory=EscalationQualityOut)


class EscalationListOut(BaseModel):
    items: list[EscalationOut] = []
    total: int = 0


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


# ── 行程规划请求（Agent 输入） ────────────────────────────────
class PlanQuestion(BaseModel):
    """主动提问：规划前向用户追问的一个问题及其答案。

    规划提交后、执行前由前端动态追问（马蜂窝 AI 路书「主动提问」差异化），
    答案随请求一并提交，由编排层并入 Planner/Critic 上下文。
    """

    question: str = Field(min_length=1, max_length=200)
    options: list[str] | None = Field(default=None, max_length=8, description="预设选项（可选）")
    answer: str | None = Field(default=None, max_length=500, description="用户回答；未回答的问题会被忽略")


class PlanRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=200)
    departure: str | None = Field(default=None, max_length=200, description="出发地（可选）；提供后 TransportAgent 会查询大交通方案并约束首日到达/末日离开安排")
    trip_type: str | None = Field(default=None, max_length=20, description="出行性质：休闲旅游/商务出差/探亲访友/亲子出游/蜜月度假（缺省按休闲旅游理解）")
    start_date: date
    end_date: date
    travelers: int = Field(default=1, ge=1)
    budget: float | None = Field(default=None, ge=0)
    preferences: list[str] = Field(default_factory=list, description="偏好，如 ['美食', '自然风光', '博物馆']")
    questions: list[PlanQuestion] = Field(default_factory=list, max_length=10, description="主动提问 Q&A（人群/节奏/避峰/备选方案），答案并入规划上下文")
    # 行程节奏档（task-pacing-leisure 结构化排程约束，联动 TimeGate 过饱和校验）
    pace: Literal["compact", "balanced", "relaxed"] | None = Field(
        default=None,
        description="行程节奏档：compact=紧凑（每日站点偏多）/ balanced=均衡（默认）/ relaxed=松弛（每日站点上限收紧+强制留白）",
    )
    # 多城市段（task-multi-city-segments）：有序城市列表，给定时按段排程并插入段间交通占位
    cities: list[str] | None = Field(
        default=None, max_length=5,
        description="多城市目的地（按行程顺序，最多 5 个）；给定时启用多段排程 + 段间交通占位 + 衔接校验",
    )
    provider: Literal["auto", "openai", "deepseek", "ollama"] = "auto"
    # 输出语种（主链路语言改造：前端 i18n locale 显式传入；未传时由
    # API 层从 Accept-Language 头解析并注入。normalize_locale 宽松归一，
    # 未知语种回退 zh-CN。注：该字段随 request_data 快照落库，Agent 所有
    # 自然语言输出（theme/description/warnings/summary 等）按此语种生成；
    # POI 名称/描述保留数据源原文，不翻译。）
    language: str | None = Field(
        default=None, max_length=32,
        description="输出语种（zh-CN / en-US；未传时后端按 Accept-Language 解析）",
    )


# ── 行程修订（方案 B：对话改行程） ─────────────────────────────
class ReviseRequest(BaseModel):
    """用户对已生成行程的自然语言修改请求。"""

    message: str = Field(min_length=2, max_length=500, description="修改意图，如「第三天太赶了，西湖只留半天，晚上想吃楼外楼」")
    provider: Literal["auto", "openai", "deepseek", "ollama"] = "auto"
    # 输出语种（与 PlanRequest.language 同契约：修订 diff 的 summary、
    # 质检报告按此语种输出；未传时 API 层按 Accept-Language 解析）
    language: str | None = Field(
        default=None, max_length=32,
        description="输出语种（zh-CN / en-US；未传时后端按 Accept-Language 解析）",
    )


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

    # 修订质控闭环（task-revise-qa-loop）：AI 生成 diff 后由 Critic 复审，
    # 未通过时可携带精确修订 fix（CriticFixSchema 同契约，plan JSON 字段名）。
    # 该单选 fix 由编排层通过 critic_fix_to_revise_diff 转换成可执行 diff，
    # 应用成功后继续下一轮复审；无 fix / 大改 / 降级时为空。
    fix: dict | None = None


# Critic fix 动作的字段名（plan JSON 名）→ ORM 字段名（ReviseAction 白名单）映射。
# CriticFixAction.fields 用 type / duration_minutes（plan JSON 约定），
# 而 ReviseAction.fields 用 stop_type / estimated_duration_minutes（ORM 名）。
# 转换后可直接走 revise_service._apply_diff 的字段白名单校验。
_FIX_FIELD_NAME_MAP = {
    "type": "stop_type",
    "duration_minutes": "estimated_duration_minutes",
}


def critic_fix_to_revise_diff(fix: dict | None) -> dict:
    """把 Critic 精确修订 fix（CriticFixSchema 结构）转成可执行的 ReviseDiff 结构。

    Rules:
    - 只接受含非空 actions 的对象；op / day_number / target / index 原样拷贝
    - fields 的键按 _FIX_FIELD_NAME_MAP 映射（type→stop_type 等），其余字段名保持
    - 转换不校验合法性（交给 _apply_diff 的原子预检）；空 actions → 返回
      {"actions": [], ...}（调用方视作「无法精确修正」）
    """
    if not isinstance(fix, dict):
        return {"actions": [], "summary": None}
    actions = fix.get("actions") or []
    out_actions = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        fields = action.get("fields") or {}
        mapped_fields = {
            _FIX_FIELD_NAME_MAP.get(k, k): v for k, v in fields.items()
        }
        mapped: dict = {"op": action.get("op"), "day_number": action.get("day_number")}
        if action.get("target") is not None:
            mapped["target"] = action["target"]
        if mapped_fields:
            mapped["fields"] = mapped_fields
        if action.get("index") is not None:
            mapped["index"] = action["index"]
        out_actions.append(mapped)
    return {
        "actions": out_actions,
        "summary": (fix.get("summary") or "Critic 修正"),
    }


class ReviseOut(BaseModel):
    """修订结果：新行程 + 摘要。"""

    trip_id: str
    summary: str
    plan: dict
    diff: list[dict] = Field(default_factory=list, description="人类可读的变更动作列表（op/day/站点/字段）")
    trace: list[AgentTraceStep]
    provider: str | None = None
    model: str | None = None
    # 修订质控闭环：Critic 复审报告（score/passed/issues/summary/fix）。
    # 健康修订必然带 quality=passed: True（或降级 degraded）；未通过但已修正的
    # 修订 quality.passed=True 且 quality.fix_applied=True。前端可据此展示质检透明度。
    quality: dict | None = None


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
    # 规划过程事件流(phase / artifact),前端阶段视图直接消费
    events: list[dict] | None = None
    # 阶段状态机(2期门控预留):collecting/assembling/reviewing/completed
    state: str | None = None


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


class GoogleLoginIn(BaseModel):
    """Google 登录：前端传回的 ID Token（Google Identity Services 的 credential）。"""

    id_token: str = Field(min_length=20, max_length=8192, description="Google ID Token (JWT)")


class UserCreateOut(UserMeOut):
    """（预留）管理员创建用户响应。"""


# ── 小红书笔记（方案 A：内容工厂） ──────────────────────────────
class XhsNoteRequest(BaseModel):
    """生成小红书笔记请求。"""

    provider: Literal["auto", "openai", "deepseek", "ollama"] = "auto"


class XhsNoteOut(BaseModel):
    """小红书笔记产物：标题/正文/话题 + 复制用完整文案 + 生成来源。"""

    title: str
    body: str
    topics: list[str] = Field(default_factory=list)
    full_text: str
    source: str = "template"  # llm / template（标注生成方式，前端提示用）
    image_spec: dict = Field(default_factory=dict)  # {width,height,ratio} 封面规格


# ── 收藏灵感夹（方案 2：task-share-token-lifecycle） ────────────
class FavoriteOut(BaseModel):
    """一条收藏：展示行程摘要 + 分享令牌（前端可直接打开分享页）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    title: str
    destination: str
    start_date: date
    end_date: date
    share_token: str | None = None
    created_at: datetime


class FavoriteListOut(BaseModel):
    items: list[FavoriteOut]
    total: int


# ── 行中费用分摊（task-expense-split-mini：Stippl/MonkeyTravel 行中一体化） ──
class ExpenseIn(BaseModel):
    """新增一条费用记录（金额/类别/支付人/备注）。"""

    category: Literal["food", "transport", "hotel", "attraction", "shopping", "other"] = "other"
    amount: float = Field(gt=0, description="实际花费金额（元，>0）")
    payer: str = Field(default="", max_length=50, description="支付人姓名（自由文本；空串=未指定）")
    note: str | None = Field(default=None, max_length=200, description="备注（≤200 字）")


class ExpenseOut(BaseModel):
    """一条费用记录（响应）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    category: str
    amount: float
    payer: str
    note: str | None = None
    created_at: datetime


class ExpenseBalanceOut(BaseModel):
    """费用分摊汇总：总额 + 人均结余。

    - ``total``：全部记录金额合计（含未指定支付人的记录）；
    - ``per_person``：指定了支付人的记录，按支付人聚合 ÷ 行程人数（travelers）得出
      人均应摊；结余 = 支付人已付 - 人均应摊（正=别人欠他，负=他欠别人）；
    - ``unassigned``：payer 为空串的记录金额合计（不参与分摊，仅计入 total）。
    """

    trip_id: str
    travelers: int
    total: float = 0.0
    per_person: float = 0.0
    balances: dict[str, float] = Field(default_factory=dict)  # payer → 结余
    unassigned: float = 0.0
    count: int = 0


# ── 对话式行程助手（B 期：会话 + 消息） ──────────────────────────
class ChatSessionCreate(BaseModel):
    """创建会话：可选标题与初始上下文（如关联 trip_id / 目的地）。"""

    title: str | None = Field(default=None, max_length=200, description="会话标题；缺省取首条消息摘要")
    context: dict | None = Field(default=None, description="会话级上下文（如关联 trip_id / 目的地）")


class ChatSessionOut(BaseModel):
    """会话列表/详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    context: dict | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionListOut(BaseModel):
    items: list[ChatSessionOut]
    total: int


class ChatMessageOut(BaseModel):
    """会话内一条消息。

    role: user / assistant / tool。
    content: 文本内容；tool_call / tool_result 为可选 JSON（工具调用记录）。
    error: 可选；assistant 失败时记录摘要。
    """

    id: str
    session_id: str
    role: str
    content: str = ""
    tool_call: dict | None = None
    tool_result: dict | None = None
    error: str | None = None
    created_at: datetime


class ChatMessageListOut(BaseModel):
    items: list[ChatMessageOut]
    total: int


class ChatSendIn(BaseModel):
    """发送一条用户消息。

    message 必填（1-2000 字符）；provider 可选（对齐 PlanRequest 默认 auto）。
    """

    message: str = Field(min_length=1, max_length=2000, description="用户输入（文本）")
    provider: str = "auto"

