"""SQLAlchemy ORM 模型：行程规划领域实体。"""
from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid4())


# TripDay.date 属性与类型名 `date` 同名，SQLAlchemy 在类命名空间求值注解时
# 会被列对象遮蔽，导致 `Mapped[date | None]` 解析失败 —— 使用模块级别名避开。
_Date = date


class Trip(Base):
    """一趟旅行（聚合根）。"""

    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    travelers: Mapped[int] = mapped_column(Integer, default=1)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    days: Mapped[list[TripDay]] = relationship(
        back_populates="trip", cascade="all, delete-orphan", order_by="TripDay.day_number"
    )


class TripDay(Base):
    """行程中的一天。"""

    __tablename__ = "trip_days"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[_Date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    trip: Mapped[Trip] = relationship(back_populates="days")
    stops: Mapped[list[Stop]] = relationship(
        back_populates="day", cascade="all, delete-orphan", order_by="Stop.order_index"
    )


class Stop(Base):
    """每日行程中的一个站点（景点/餐厅/住宿）。"""

    __tablename__ = "stops"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    day_id: Mapped[str] = mapped_column(ForeignKey("trip_days.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stop_type: Mapped[str] = mapped_column(String(20), default="attraction")  # attraction/food/hotel
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 供地图/导出使用的可选元数据
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    day: Mapped[TripDay] = relationship(back_populates="stops")


class TripPlan(Base):
    """Agent 生成的完整行程方案（JSON 快照 + 轨迹）。"""

    __tablename__ = "trip_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    plan_data: Mapped[dict] = mapped_column(JSON, nullable=False)  # 完整行程 JSON
    trace: Mapped[list | None] = mapped_column(JSON, nullable=True)  # T-A-O 轨迹
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # openai/deepseek/ollama
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")  # running/completed/failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trip: Mapped[Trip] = relationship()


class PlanTask(Base):
    """异步规划任务：追踪 Agent 执行进度，结果回填。"""

    __tablename__ = "plan_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    request_data: Mapped[dict] = mapped_column(JSON, nullable=False)  # PlanRequest 快照
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending/running/completed/failed
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace: Mapped[list | None] = mapped_column(JSON, nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)