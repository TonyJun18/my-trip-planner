# ── 部署文档：Docker 一键部署 my-trip-planner ────────────────

> 仓库根目录的 `docker-compose.yml` 定义了三服务拓扑：**Postgres 17 + FastAPI 后端 + nginx 前端**。
> 前端由 nginx 托管，并把 `/api` 反代到后端容器——对外只暴露 `8080` 一个端口。

## 拓扑

```
浏览器 ── :8080 ──> nginx (frontend) ── /api ──> backend:8090 ──> db:5432 (postgres:17)
```

- `frontend`：构建 Vue3 静态资源 → nginx 托管；SPA history 路由回退 + `/api` 反代
- `backend`：uvicorn 单进程；启动时 `create_all` 建表（有 alembic/ 迁移，见下文说明）
- `db`：Postgres 17，数据持久化到 named volume `pgdata`

## 前置要求

- Docker 27+ 与 Docker Compose v2（`docker compose version` 验证）
- 端口：`8080`（前端）、`5433`（db，开发调试用；生产可去掉 ports 段。本机已有 Postgres 时用 `POSTGRES_PORT` 覆盖）

## 快速开始

```bash
# 1. 准备环境变量（JWT_SECRET 必须改成随机值；LLM/高德/Tavily key 按需填）
cp .env.example .env
#   JWT_SECRET=$(python3 -c "import secrets;print(secrets.token_hex(32))") 写入 .env 的 JWT_SECRET=

# 2. 一键构建 + 启动
docker compose up -d --build

# 3. 验证
curl -s http://localhost:8080/api/v1/health
# 浏览器打开 http://localhost:8080 → 注册 → 登录 → AI 规划行程
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `JWT_SECRET` | ✅ | 生产必须设置随机 64 位 hex；不设则进程重启后 token 失效 |
| `POSTGRES_PASSWORD` | 可选 | 默认 `postgres`（仅本机演示；公网部署请改） |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | 按需 | 配置后 LLM 规划走真实模型；都不配 → 规划接口报错（设计如此，见 README 已知局限） |
| `AMAP_API_KEY` | 可选 | 高德 POI/天气；不配自动降级 Tavily / wttr.in |
| `TAVILY_API_KEY` | 可选 | 降级搜索源 |

> compose 默认 `ENV=prod`、`DEBUG=false`、`LOG_LEVEL=INFO`；`CORS_ORIGINS` 已限定为 `http://localhost:8080`。

## 数据库迁移说明

- 应用启动时调用 `init_db()`（`create_all`）——开发友好，但**不会**执行 alembic 的增量迁移。
- 若后续 schema 演进（如新增表列），请用迁移执行：
  ```bash
  # 进入 backend 容器执行（生产环境需谨慎，先备份）
  docker compose exec backend uv run alembic upgrade head
  ```
- alembic 迁移文件位于 `backend/alembic/versions/`。

## 常用运维

```bash
docker compose ps                 # 三服务状态
docker compose logs -f backend    # 看后端日志
docker compose restart backend    # 重启后端
docker compose down               # 停止（保留数据卷）
docker compose down -v            # 停止并删除数据卷（⚠️ 丢数据！）
```

## 已知限制（诚实清单）

1. **单进程 uvicorn**：未配 gunicorn/多 worker（Agent 规划为 CPU/IO 混合任务，生产扩多 worker 需注意任务队列在内存中，多进程会丢队列状态）。
2. **任务队列在内存**：重启后端会丢失正在进行的规划任务（与本地开发一致）。
3. **图片/PDF 导出在前端完成**（html2canvas + jsPDF），不需要额外后端依赖。
4. **没有 HTTPS**：本 compose 面向内网/演示；公网部署请在前面挂 Caddy/Traefik。

## 验收

```bash
docker compose config -q         # 配置合法（无输出 = 通过）
docker compose up -d --build     # 构建并启动
curl -s http://localhost:8080/api/v1/health   # {"status":"ok",...}
```