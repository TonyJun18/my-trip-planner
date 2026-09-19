# 智能旅行助手（my-trip-planner）

一个演示 **多 Agent 协作行程规划**的智能旅行应用（FastAPI + LangGraph + Vue3）。

## 核心功能

1. **多 Agent 智能规划**：用户输入目的地、日期、偏好，**4 个角色 Agent 协作**生成完整行程——
   `AttractionSearchAgent`（景点搜索专家）、`WeatherQueryAgent`（天气查询专家）、
   `HotelAgent`（酒店推荐专家）、`PlannerAgent`（行程规划专家）。
2. **单一职责提示词**：每个搜索 Agent 只做一件事——理解偏好/需求 → 选关键词 → 调工具；
   PlannerAgent 不调用工具，只整合团队产出，输出经 Pydantic 强校验的行程 JSON（失败自动自纠正）。
3. **真实数据搜索**：景点/酒店/餐厅用**高德地图 POI**（`AMAP_API_KEY`），天气用**高德天气**；
   未配置高德 key 时自动降级 Tavily Search + Nominatim / wttr.in——没有硬编码假数据。
4. **并行编排**：三个采集 Agent 并行执行（`asyncio.gather`），快且互不阻塞；
   编排层补充餐饮，Planner 最后统一整合，预算按真实站点费用代码校准。
5. **异步规划任务**：规划提交后立即返回 `task_id`，前端轮询实时展示多 Agent 的 T-A-O 轨迹（含 agent 名）。
6. **LLM 输出强校验**：所有 Agent 最终行程 JSON 都经过 Pydantic Schema 校验（字段/类型/日期/预算），失败自动让 LLM 自纠正（最多 3 次）。
7. **LLM 容错**：统一重试（指数退避）+ 进程内熔断器，保护下游 LLM。
8. **预算计算**：按站点类型（景点/餐饮/住宿）自动汇总预算明细。
9. **行程管理**：行程 / 日程 / 站点的增删改查（CRUD）。
10. **轻量多用户隔离**：前端自动生成用户 token 随请求头发送，行程与任务按用户隔离。

## 技术栈

- **FastAPI** — Web 框架，自动生成 OpenAPI 文档（`/docs`）
- **LangGraph / LangChain** — Agent 状态图与工具编排（多 Agent 流水线）
- **PostgreSQL 17** — 数据库（Docker 部署）
- **SQLAlchemy 2 (async) + asyncpg** — ORM 与异步驱动
- **Alembic** — 数据库迁移
- **Pydantic v2 + pydantic-settings** — 数据校验与配置管理
- **高德开放平台（POI / 天气）+ Tavily + wttr.in** — 真实数据源
- **pytest + httpx** — 测试（FakeLLM 测试替身，不消耗 token、不依赖网络）

## 目录结构

```
backend/
├── app/
│   ├── main.py              # FastAPI 应用工厂（lifespan 启动规划执行器）
│   ├── run_server.py        # uvicorn 启动入口
│   ├── common/config.py     # pydantic-settings 配置
│   ├── core/                # logging / exceptions / database / auth(用户隔离)
│   ├── models/              # SQLAlchemy ORM（Trip/TripDay/Stop/TripPlan/PlanTask）
│   ├── schemas/             # Pydantic 请求/响应模型 + Agent 输出强校验
│   ├── services/            # 业务逻辑（trip / budget / planning 异步任务）
│   ├── agent/               # 多 Agent（agents.py 编排 / tools.py 高德·Tavily·天气 / providers.py LLM）
│   └── api/v1/              # 路由（health / trips / planner）
├── alembic/                 # 数据库迁移
├── tests/                   # pytest 测试
├── pyproject.toml           # uv 工程配置
├── .env / .env.example      # 环境变量
└── uv.lock
```

### 前端（可选）

```
frontend/                    # Vue3 + Vite + Element Plus + Leaflet
```

## 快速启动

### 1. 数据库（Docker）

```bash
docker run -d --name postgres -p 5432:5432 \
  -e POSTGRES_PASSWORD=your_password \
  -v pgdata:/var/lib/postgresql/data \
  postgres:17

docker exec -it postgres psql -U postgres -c \
  "CREATE DATABASE my_trip_planner;"
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 必填：
#   DATABASE_URL         数据库连接串
#   TAVILY_API_KEY       Tavily 搜索 key（https://tavily.com）
#   DEEPSEEK_API_KEY 或 OPENAI_API_KEY（或本地 Ollama）
# 可选：
#   DEFAULT_LLM_PROVIDER auto/deepseek/openai/ollama
```

### 3. 安装依赖并迁移

```bash
uv sync                 # 安装依赖
uv run alembic upgrade head   # 应用数据库迁移
```

### 4. 启动服务

```bash
uv run python app/run_server.py
# 或
uv run uvicorn app.main:app --reload
```

访问 http://127.0.0.1:8090/docs 查看 API 文档。

前端（可选）：

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `ENV` | 运行环境（dev/staging/prod） | `dev` |
| `HOST` / `PORT` | 服务监听地址/端口 | `127.0.0.1` / `8090` |
| `DATABASE_URL` | 数据库连接串（asyncpg） | 必填 |
| `DEFAULT_LLM_PROVIDER` | 模型提供商（auto/deepseek/openai/ollama） | `auto` |
| `DEEPSEEK_API_KEY` | DeepSeek key | 空 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | OpenAI 兼容接口 | 空 / `gpt-4o-mini` |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | 本地 Ollama | `http://localhost:11434` / `qwen2.5:7b` |
| `TAVILY_API_KEY` | Tavily 搜索 key（高德未配置时降级源） | 空 |
| `AMAP_API_KEY` | 高德开放平台 Web 服务 key（POI 搜索/天气，https://lbs.amap.com 申请） | 空 |
| `AGENT_MAX_ITERATIONS` | Agent 最大循环次数 | `10` |
| `AGENT_MAX_CORRECTIONS` | LLM 输出校验失败的最大自纠正次数 | `3` |
| `LOG_LEVEL` | 日志级别 | `DEBUG` |
| `JWT_SECRET` | JWT 签名密钥（生产必配） | 进程级随机 |
| `JWT_EXPIRE_MINUTES` | token 有效期（分钟） | `10080`（7 天） |
| `CORS_ORIGINS` | 允许的跨域来源 | `*` |

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/register` | 注册（邮箱或手机号 + 密码） |
| POST | `/api/v1/auth/login` | 登录（邮箱或手机号 + 密码），返回 JWT |
| GET | `/api/v1/auth/me` | 当前用户信息（需登录） |
| GET | `/api/v1/health` | 健康检查（含数据库连通性/延迟） |
| GET | `/api/v1/trips` | 行程列表（分页，按用户隔离） |
| POST | `/api/v1/trips` | 创建行程 |
| GET | `/api/v1/trips/{id}` | 行程详情 |
| PATCH | `/api/v1/trips/{id}` | 更新行程 |
| DELETE | `/api/v1/trips/{id}` | 删除行程 |
| POST | `/api/v1/trips/{id}/days` | 添加日程 |
| POST | `/api/v1/trips/{id}/days/generate` | 按日期范围批量生成日程 |
| POST | `/api/v1/trips/days/{day_id}/stops` | 添加站点 |
| GET | `/api/v1/trips/{id}/budget` | 预算明细 |
| POST | `/api/v1/planner/plan` | **提交 AI 规划任务（异步，需登录）** |
| GET | `/api/v1/planner/tasks/{task_id}` | **轮询规划任务状态（含实时 trace，需登录）** |

> 除 `/auth/*` 与 `/health` 外，所有接口都需要 `Authorization: Bearer <token>`。

### 注册 / 登录示例

```bash
# 注册（邮箱或手机号至少一个）
curl -X POST http://127.0.0.1:8090/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your_password", "display_name": "小明"}'
# → { "access_token": "eyJ...", "token_type": "bearer", "user": {...} }

# 登录
curl -X POST http://127.0.0.1:8090/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"account": "you@example.com", "password": "your_password"}'

# 用 token 访问受保护接口
curl http://127.0.0.1:8090/api/v1/trips \
  -H "Authorization: Bearer eyJ..."
```

### 调用 Agent 规划行程（异步）

```bash
# 先登录获取 token
TOKEN=$(curl -s -X POST http://127.0.0.1:8090/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"account": "you@example.com", "password": "your_password"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -X POST http://127.0.0.1:8090/api/v1/planner/plan \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "destination": "杭州",
    "start_date": "2026-10-01",
    "end_date": "2026-10-03",
    "travelers": 2,
    "budget": 3000,
    "preferences": ["美食", "自然"]
  }'

# → { "task_id": "xxx", "status": "pending", ... }

curl http://127.0.0.1:8090/api/v1/planner/tasks/xxx \
  -H "Authorization: Bearer $TOKEN"
# → { "task_id": "xxx", "status": "completed", "trip_id": "...", "plan": {...}, "trace": [...] }
```

## T-A-O Agent 工作原理

```
用户请求
   │
   ▼
┌─► agent_node（Thought/Action）
│     │
│     ├── 需要信息？ ──► 调用 search_attractions / compute_budget（真实数据）
│     │                        │
│     │                        ▼
│     └── 信息足够？      tools_node（执行工具，回填 Observation）
│                              │
│                              └── Observation 回填 ──┘
│
└──► 校验通过？ ──► 输出最终行程 JSON（Pydantic 强校验）
         │失败
         ▼
   反馈 LLM 自纠正（最多 AGENT_MAX_CORRECTIONS 次）
```

- `agent_node`：调用 LLM（带重试 + 熔断），产出下一步动作（工具调用或最终计划）
- `tools_node`：真正执行工具（Tavily 搜索 + 地理编码），把结果作为 Observation 回填
- 循环直到产出通过校验的完整计划，或达到最大迭代次数
- 最终 JSON 经 `PlanSchema` 强校验，失败自动让 LLM 自纠正

**LLM Provider**：配置 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`（或本地 Ollama）后即可使用真实模型。
未配置任何 key 时，`/planner/plan` 返回明确错误（**不再有 mock 降级**）。

## 测试

```bash
# 需要本地 Postgres（从 DATABASE_URL 推导测试库，或用 TEST_DATABASE_URL 指定）
uv run pytest
```

覆盖：health、行程 CRUD、日程/站点、预算、异步规划任务全链路（FakeLLM 测试替身）、
LLM 输出 schema 校验与自纠正、owner 用户隔离。测试无需真实 API key / 网络。

## 数据库迁移

```bash
uv run alembic revision --autogenerate -m "描述"   # 生成迁移
uv run alembic upgrade head                        # 应用
uv run alembic downgrade -1                        # 回滚
```