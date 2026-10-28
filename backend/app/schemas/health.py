"""健康检查 Schema。"""
from __future__ import annotations

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    env: str
    database: str
    database_latency_ms: float | None = None