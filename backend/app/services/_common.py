"""service 层共享小工具（避免 planning/revise/trip 三个 service 重复实现）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import selectinload

from app.models import Trip, TripDay

# 统一 eager-load 关系，避免序列化时 async lazy load 报 MissingGreenlet
TRIP_LOADS = (selectinload(Trip.days).selectinload(TripDay.stops),)


def normalize_trace(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把多 Agent 的 trace（含 agent 名）转成前端兼容的 AgentTraceStep 结构。

    {agent, action, observation, status} → {thought: agent, action, action_input, observation}。
    """
    out = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        out.append({
            "thought": s.get("agent") or s.get("thought") or "",
            "action": s.get("action") or "",
            "action_input": s.get("action_input") or "",
            "observation": s.get("observation") or "",
        })
    return out