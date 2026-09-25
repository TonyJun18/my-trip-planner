"""健康检查。"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from sqlalchemy import text

from app.common.config import settings
from app.core.database import engine
from app.schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut, summary="健康检查")
async def health() -> HealthOut:
    """健康检查：独立连接 + 显式超时，DB 故障时返回 degraded 而非 500。

    不使用 ``get_session`` 依赖——依赖解析/提交发生在 handler 之外，
    DB 故障会直接抛 500；这里用独立连接并把 3s 超时包住，DB 假死也只
    让健康检查降级，不挂住请求。
    """
    db_status = "ok"
    latency: float | None = None
    try:
        t0 = time.perf_counter()
        async with asyncio.timeout(3):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        latency = round((time.perf_counter() - t0) * 1000, 2)
    except Exception:  # noqa: BLE001 — 健康检查必须捕获一切异常并降级报告
        db_status = "error"

    status = "ok" if db_status == "ok" else "degraded"
    return HealthOut(
        status=status,
        app=settings.APP_NAME,
        version="0.1.0",
        env=settings.ENV,
        database=db_status,
        database_latency_ms=latency,
    )