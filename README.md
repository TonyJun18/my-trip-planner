# 智能旅行助手（my-trip-planner）

一个把 **多 Agent 协作**做成 **生产级工程** 的智能旅行应用（FastAPI + LangGraph + Vue3）。
不是"调一个 LLM 生成 JSON"的 demo —— 它回答了这类系统真正难的问题：
**怎么让多个 Agent 稳定、可靠、可测试地产出结构化业务数据。**

> 核心看点（技术向）：
> - **多 Agent 单一职责编排**：3 个采集 Agent 并行（`asyncio.gather`）+ 1 个规划 Agent 只整合不调工具，
>   编排层代码补位（餐饮搜索）——不是把所有逻辑塞进一个超长 prompt
> - **Evaluator-Optimizer 质检闭环**：Planner 产出后由 TravelCriticAgent（无工具质检专家）按
>   日程/预算/地理/完整性四维评分，不过审带反馈重生成（最多 2 轮后强制定稿，质检失败自动降级放行）
> - **对话式行程修订（AI 出 diff，代码执行）**：用户自然语言改行程 → PlanReviseAgent 生成结构化
>   变更指令 diff → 编排层代码原子应用（存在性/类型/位置校验，任一失败整体回滚）
> - **LLM 输出强校验 + 失败自纠正**：所有 Agent 最终输出过 Pydantic Schema（字段/类型/日期/预算范围），
>   校验失败把错误摘要喂回 LLM 最多自纠正 3 次——LLM 输出不可信，schema 才可信
> - **系统级容错**：LLM 调用统一指数退避重试 + 进程内熔断器（滑动窗口），保护下游 LLM 不被打爆
> - **真实数据，不造假**：高德 POI/天气（未配置自动降级 Tavily + wttr.in），没有硬编码假数据
> - **可测试性当一等公民**：FakeLLM 测试替身让 30 个测试不耗 token、不依赖网络
> - **全链路可观测**：异步规划任务 + 前端实时 T-A-O（Thought-Action-Observation）轨迹

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
7. **行程质检（Evaluator-Optimizer）**：Planner 产出后由 `TravelCriticAgent` 从日程/预算/地理/完整性四维审查，
   不过审把结构化 issues 反馈给 Planner 重生成，最多 `AGENT_MAX_REVIEW_ROUNDS`（默认 2）轮后强制定稿；
   质检自身失败自动降级「通过放行」，绝不阻断主流程。
8. **对话式行程修订（方案 B）**：`POST /trips/{id}/revise` 用一句话改行程——`PlanReviseAgent` 把用户请求解析为
   结构化 diff（replace/add/remove/reorder），编排层代码**原子应用**（目标/类型/位置校验，任一失败整体回滚，
   数据库事务不提交），预算由代码重算，前端详情页「让 AI 调整行程」直接对话操作。
9. **LLM 容错**：统一重试（指数退避）+ 进程内熔断器，保护下游 LLM。
10. **预算计算**：按站点类型（景点/餐饮/住宿）自动汇总预算明细。
11. **行程管理**：行程 / 日程 / 站点的增删改查（CRUD）。
12. **轻量多用户隔离**：前端自动生成用户 token 随请求头发送，行程与任务按用户隔离。

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
| `AGENT_MAX_REVIEW_ROUNDS` | 行程质检（Critic）最大评审轮数，过后强制定稿 | `2` |
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

## 多 Agent 架构

### 规划主链路（含质检闭环）

```
                        用户输入（目的地/日期/人数/预算/偏好）
                                      │
                                      ▼
                              ┌─────────────────┐
                              │  编排层（代码）    │
                              │  run_planning_   │
                              │  agents()        │
                              └─────────────────┘
                                      │  asyncio.gather（并行）
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │ AttractionSearch │   │ WeatherQueryAgent │   │   HotelAgent     │
   │ Agent（景点专家）  │   │ （天气专家·纯工具） │   │（酒店推荐专家）    │
   │  偏好→关键词→POI  │   │  城市→天气预报    │   │ 需求→关键词→POI   │
   └──────────────────┘   └──────────────────┘   └──────────────────┘
              │                     │                    │
              ▼                     ▼                    ▼
      ┌──────────────────────────────────────────────────────┐
      │              编排层代码补齐（非 LLM）：                 │
      │  · 餐饮 POI 搜索（美食是行程必备）                      │
      │  · 预算用 compute_budget 代码校准（LLM 估值不可信）     │
      └──────────────────────────────────────────────────────┘
                                      │
                                      ▼
                        ┌─────────────────────────┐
                        │  PlannerAgent（规划专家） │
                        │  · 不调用任何工具         │
                        │  · 只整合团队产出         │
                        │  · 输出经 PlanSchema     │
                        │    强校验 + 失败自纠正    │
                        └─────────────────────────┘
                                      │
                                      ▼
                        ┌─────────────────────────┐
                        │ TravelCriticAgent（质检） │
                        │  · 无工具，按 schedule / │
                        │    budget / geography / │
                        │    logistics 四维打分    │
                        │  · 输出 CritiqueSchema   │
                        └─────────────────────────┘
                           │                │
             未通过(score<80)│                │通过 / 达最大轮数
                           ▼                ▼
              带 issues 反馈 Planner   完整行程 JSON（落库）
              重新生成（≤2 轮后强制
              定稿；Critic 故障降级放行）
```

### 修订链路（方案 B：对话改行程）

```
用户：一句话修改请求（如「第三天太赶了，西湖只留半天」）
                    │
                    ▼
        ┌─────────────────────────┐
        │   PlanReviseAgent       │
        │  · 用户消息 + 当前行程 →  │
        │    结构化 diff 指令      │
        │  · 输出经 ReviseDiff     │
        │    强校验 + 自纠正       │
        └─────────────────────────┘
                    │  diff（replace / add / remove / reorder）
                    ▼
        ┌─────────────────────────┐
        │  编排层代码（原子应用）    │
        │  · 预检全部动作（目标/    │
        │    类型/位置）            │
        │  · 任一失败 → 整体回滚    │
        │  · 预算由代码重算         │
        └─────────────────────────┘
                    │
                    ▼
            新行程落库 + 变更摘要
```

**为什么这样拆**（而不是一个超长 prompt 大杂烩）：
- **单一职责**：每个 Agent 只做一件事，提示词极简（< 30 行），行为可预期
- **并行**：三个采集 Agent 互不依赖，`asyncio.gather` 秒级完成，可水平扩展
- **确定性兜底**：天气是"城市→数据"的确定性路径，干脆做成纯工具（零 token、零幻觉）；
  预算是纯计算，交给 `compute_budget` 代码——**LLM 只做它擅长的"理解 + 编排"，数学和事实交给代码**
- **编排层补位**：Agent 不会主动想起"还要吃顿饭"，编排层用代码补上餐饮——不依赖 prompt 自觉
- **质检用独立角色**：Evaluator（Critic）与 Generator（Planner）是不同的 system prompt + 独立调用，
  避免共享盲点——生成者不会自己审自己的错
- **修订"AI 出题、代码执行"**：PlanReviseAgent 只产 diff 指令，落库由代码原子应用——
  任一动作非法就整体回滚，杜绝 LLM 直接改库带来的半生效状态

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

## 已知局限（诚实清单）

做成生产级工程不等于没有短板，清楚写在这里：

| 局限 | 影响 | 状态 / 可选改进 |
|------|------|----------|
| 高德免费 POI 不返回价格，酒店/景点 `estimated_cost` 多为 0 | 预算里 hotel 项偏空壳，只按门票类估算 | 未解决：接付费 POI / 携程或 Booking 类价格源（有成本与合规考量） |
| 无预订/支付闭环 | 用户只能拿到"计划"，不能直接下单 | **方案 C（未做）**：接分销商 API，做成真正的转化产品 |
| LLM 规划质量受模型能力上限约束 | 复杂定制（如"避开周一闭馆"）可能不完美 | ✅ **方案 A 缓解**：TravelCriticAgent 四维质检 + 反馈重生成，业务不合理问题可被拦截修正 |
| 多 Agent 编排是"管道式"（pipeline），非"协商式" | Agent 间不互相质疑/讨论 | ✅ **方案 A 部分解决**：plan-then-review 闭环，Critic 会质疑 Planner 的产出 |
| 行程是静态快照，旅游中不可交互 | 用户无法实时改路线 | ✅ **方案 B 缓解**：详情页"让 AI 调整行程"对话式修订（AI 出 diff，代码原子执行） |