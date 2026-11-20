"""最小漏斗埋点事件（task-launch-deploy-eval §2）。

与既有「意图埋点」（日志版，不落库）分离：
- 本表只接收 5 类漏斗白名单事件（page_view/register/plan_submitted/
  plan_completed/share_created），由 ``POST /analytics/events`` 的
  ``dedicated: true`` 分支写入；
- ``user_id`` / ``trip_id`` 可为空（匿名访问也记录），故不设外键，
  避免匿名/已删行程的事件被拒写；
- ``payload`` 存来源页/渠道等弱结构化信息（JSON）。
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid4())


class AnalyticsEvent(Base):
    """一条漏斗事件（追加写，不更新不删除）。"""

    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_events_name_created", "event_name", "created_at"),
        Index("ix_analytics_events_anonymous_session", "anonymous_session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_name: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    anonymous_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
