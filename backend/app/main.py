"""FastAPI 应用工厂。"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.common.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    setup_logging()
    logger.info("启动 %s env=%s debug=%s", settings.APP_NAME, settings.ENV, settings.DEBUG)
    if settings.ENV == "dev":
        from app.core.database import init_db

        await init_db()
    # 启动规划任务执行器
    from app.services.planning_service import get_executor

    executor = get_executor()
    executor.start()
    logger.info("规划任务执行器已启动")
    yield
    await executor.stop()
    logger.info("关闭 %s", settings.APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title="My Trip Planner API",
        description="智能旅行助手 —— LangGraph Thought-Action-Observation Agent + FastAPI + PostgreSQL",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    origins = settings.CORS_ORIGINS
    if isinstance(origins, str):
        origins = [origins]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"app": settings.APP_NAME, "docs": "/docs", "api": "/api/v1"}

    return app


app = create_app()