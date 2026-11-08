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
from app.core.security import assert_secure_jwt_secret

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    setup_logging()
    # 启动前配置校验：非 dev 环境缺 JWT_SECRET 直接拒绝启动（fail fast），
    # 避免「重启后全员被登出」的生产事故被误判为登录过期。
    assert_secure_jwt_secret()
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

    # 请求级 trace_id（contextvar + 响应头 X-Trace-ID；日志自动附加）
    from app.core.tracing import RequestIdMiddleware

    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    # ── WebSocket：契约是根路径 /ws/*，不能并进 /api/v1 ─────────────
    # 前端 WS_BASE、vite proxy '/ws'、nginx `location /ws/`、README 契约都按 /ws/*
    # 编写；若把 ws.router 并进 api_router，真实路径会变成 /api/v1/ws/*，
    # 所有握手被 403 拒绝且**静默退化为轮询**（2026-11-08 实测定位）。
    from app.api.v1.chat import ws_chat
    from app.api.v1.ws import router as ws_router

    app.include_router(ws_router)  # 自带 prefix="/ws" → /ws/planner/*, /ws/trips/*/collab
    # 对话流式推送：chat.router 内的 WS 路径会带 /chat 前缀，前端用的是 /ws/chat/{id}，
    # 故在同一 handler 上补一条根路径路由（避免为此重构 chat 路由表）。
    app.add_api_websocket_route("/ws/chat/{session_id}", ws_chat)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"app": settings.APP_NAME, "docs": "/docs", "api": "/api/v1"}

    return app


app = create_app()