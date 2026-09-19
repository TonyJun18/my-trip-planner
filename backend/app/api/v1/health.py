"""健康检查。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import settings
from app.core.database import get_session
from app.schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut, summary="健康检查")
async def health(db: AsyncSession = Depends(get_session)) -> HealthOut:
    db_status = "ok"
    latency: float | None = None
    try:
        t0 = time.perf_counter()
        await db.execute(text("SELECT 1"))
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