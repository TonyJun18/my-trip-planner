"""pytest 共享夹具：测试数据库 + 应用客户端。

数据库地址来自环境变量（不再硬编码密码）：
- ``TEST_DATABASE_URL``: 完整测试库连接串（优先级最高）
- 未设置时从 ``DATABASE_URL`` 推导：换库名 + ``_test`` 后缀

测试库 session 级创建/销毁。
"""
from __future__ import annotations

import os
import re
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 从 backend/.env 加载 DATABASE_URL（直接命令行 pytest 时无需手动 export）
load_dotenv()


# ── 测试库连接配置 ─────────────────────────────────────────
def _test_dsn() -> str:
    if os.getenv("TEST_DATABASE_URL"):
        return os.getenv("TEST_DATABASE_URL")  # type: ignore[return-value]
    base = os.getenv("DATABASE_URL", "")
    if not base:
        raise RuntimeError("缺少 DATABASE_URL 环境变量（测试需要真实 Postgres）")
    # postgresql+asyncpg://user:pw@host:port/dbname → 换 dbname 加 _test_uuid
    suffix = uuid.uuid4().hex[:8]
    return re.sub(r"/([^/]+)$", f"/test_trip_{suffix}", base)


TEST_DSN = _test_dsn()


def _admin_dsn() -> str:
    """从 TEST_DSN 推导 admin 连接（连 postgres 库做 create/drop）。"""
    return re.sub(r"/([^/]+)$", "/postgres", TEST_DSN)


def _asyncpg_dsn(dsn: str) -> str:
    """asyncpg 不接受 sqlalchemy 的 +asyncpg 前缀，去掉它。"""
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_test_db():
    """session 级：建测试库；结束时删除。"""
    import asyncpg

    admin_dsn = _asyncpg_dsn(_admin_dsn())
    db_name = TEST_DSN.rsplit("/", 1)[-1]

    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()

    yield

    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def test_engine():
    """function 级引擎：创建/使用/销毁都在同一 event loop，避免 asyncpg 跨 loop 复用。"""
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(TEST_DSN, poolclass=NullPool)
    # 建表 + 清空业务表
    from app.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("TRUNCATE TABLE users, trips, trip_days, stops, trip_plans, plan_tasks, trip_comments, stop_votes, user_profiles CASCADE")
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_engine) -> AsyncGenerator[AsyncClient]:
    """用 ASGITransport + 依赖覆盖跑应用（真实 DB，无网络端口）。"""
    from app.core.database import get_session
    from app.main import app

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def plan_executor(test_engine):
    """每个测试：用「测试库」的 session factory 创建并启动规划执行器。

    ASGITransport 不触发 lifespan，因此这里手动装配；结束后停止并重置
    单例，避免跨测试复用已绑定旧 event loop 的 worker。
    """
    from app.services import planning_service

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    executor = planning_service.get_executor(factory)
    executor.start()
    yield executor
    await executor.stop()
    planning_service._executor = None  # 重置单例


@pytest_asyncio.fixture
async def auth_user(client):
    """注册一个测试用户，返回 (user_info, auth_headers)。"""
    import uuid

    email = f"user-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test1234", "display_name": "测试用户"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["user"], {"Authorization": f"Bearer {data['access_token']}"}