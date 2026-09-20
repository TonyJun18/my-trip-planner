"""Agent 输出 Schema：LLM 生成的行程 JSON 强校验。

真实 LLM 输出不可信 —— 字段缺失、类型错误、日期格式错乱都可能导致
落库失败或前端渲染崩溃。所有 Agent 最终输出必须通过这里校验后才能
持久化。校验失败时把错误摘要反馈给 LLM 让其自纠正。
"""
from __future__ import annotations

from datetime import date as _Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StopSchema(BaseModel):
    """行程站点。"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200)
    type: Literal["attraction", "food", "hotel"] = "attraction"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    estimated_cost: float = Field(default=0.0, ge=0)
    duration_minutes: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=1000)


class DaySchema(BaseModel):
    """一天的行程。"""

    model_config = ConfigDict(extra="ignore")

    day_number: int = Field(ge=1)
    date: _Date | None = None
    theme: str | None = Field(default=None, max_length=200)
    stops: list[StopSchema] = Field(default_factory=list, max_length=20)


class HotelSchema(BaseModel):
    """酒店推荐候选（来自 HotelAgent 搜索结果，随 plan 一并输出/落库）。"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200)
    type: Literal["hotel"] = "hotel"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    estimated_cost: float = Field(default=0.0, ge=0)
    description: str | None = Field(default=None, max_length=1000)
    address: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=50)
    source_url: str | None = Field(default=None, max_length=500)
    rating: float | None = Field(default=None, ge=0, le=5)


class BudgetSchema(BaseModel):
    """预算汇总。"""

    model_config = ConfigDict(extra="ignore")

    total_estimated: float = Field(ge=0)
    by_type: dict[str, float] = Field(default_factory=dict)
    currency: str = "CNY"


class PlanSchema(BaseModel):
    """LLM 最终输出的完整行程 JSON。"""

    model_config = ConfigDict(extra="ignore")

    destination: str = Field(min_length=1, max_length=200)
    days: list[DaySchema] = Field(default_factory=list, min_length=1, max_length=31)
    budget: BudgetSchema = Field(default_factory=BudgetSchema)
    # 酒店推荐候选（由编排层代码回填，LLM 不需要输出；校验通过后仍保留）
    hotels: list[HotelSchema] = Field(default_factory=list, max_length=20)
    # 降级/告警信息：如"酒店搜索失败，已用通用描述替代"
    warnings: list[str] = Field(default_factory=list, max_length=20)


class CritiqueIssueSchema(BaseModel):
    """质检发现的一个具体问题。"""

    model_config = ConfigDict(extra="ignore")

    severity: Literal["critical", "warning", "info"] = "warning"
    """critical=必须修改 / warning=建议修改 / info=提示。"""
    category: Literal["schedule", "budget", "geography", "logistics", "info"] = "info"
    """问题类别：时间日程 / 预算 / 地理路线 / 内容完整性 / 一般信息。"""
    message: str = Field(min_length=1, max_length=500)
    suggestion: str | None = Field(default=None, max_length=500)
    day_number: int | None = Field(default=None, ge=1)


class CritiqueSchema(BaseModel):
    """行程质检报告（TravelCriticAgent 输出）。"""

    model_config = ConfigDict(extra="ignore")

    score: int = Field(ge=0, le=100)
    """综合评分（0-100）。"""
    passed: bool = False
    """score >= 80 视为通过。"""
    issues: list[CritiqueIssueSchema] = Field(default_factory=list, max_length=20)
    summary: str | None = Field(default=None, max_length=300)


def validate_plan(data: dict) -> dict:
    """校验 LLM 输出并返回「可 JSON 序列化」的干净 dict（丢弃多余字段）。

    Raises:
        pydantic.ValidationError: 校验失败（调用方决定如何反馈/重试）。
    """
    validated = PlanSchema.model_validate(data)
    return validated.model_dump(mode="json")


def validate_critique(data: dict) -> dict:
    """校验 TravelCriticAgent 输出的质检报告。

    Raises:
        pydantic.ValidationError: 校验失败（调用方决定如何反馈/重试）。
    """
    validated = CritiqueSchema.model_validate(data)
    return validated.model_dump(mode="json")