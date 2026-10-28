"""Agent 交互 Schemas：规划请求 / 异步任务 / 对话式修订。

注意：本模块与 ``app.schemas.plan``（Agent 输出的 PlanSchema 强校验）是两个
不同域——这里是「用户 ↔ 编排层」的请求/响应模型，plan.py 是「LLM 输出 ↔
落库」的数据契约。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    summary: str | None = Field(default=None, max_length=300)
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