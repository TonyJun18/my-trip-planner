# ── my-trip-planner · 后端镜像 ───────────────────────────────
# 生产部署用：Python 3.13 + uv 安装依赖 + 非 root 用户运行
# 构建：docker build -f backend/Dockerfile -t my-trip-planner-backend backend
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv 官方安装（固定版本，保证可复现）
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存（依赖层仅在清单变化时重建）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 再复制应用代码
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

# 非 root 用户（安全基线）
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8090

# 启动前自动执行数据库迁移（幂等：alembic upgrade head 只应用未执行的迁移），随后起 uvicorn
# 注意：依赖装在 venv 里，uvicorn 要用 .venv/bin/ 下的可执行文件（uv run 只包单条命令）
CMD ["sh", "-c", "uv run alembic upgrade head && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090"]