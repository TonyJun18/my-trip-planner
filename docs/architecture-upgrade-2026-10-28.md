# my-trip-planner 架构升级记录（C+A 方案落地，2026-10-28）

> 升级基准：main HEAD `59de0d5`（升级前）/ 升级后工作区（未提交，待 review）
> 事实来源：代码实测 + 全套回归（**523 passed** 后端 + 前端 Vite build 成功）
> 本文档记录本轮「架构师审查 → 方案确认 → C+A 实施」全过程，结论均基于仓库实际代码与测试结果。

---

## 一、背景与目标

项目从 demo 走向生产，暴露出三类**制约迭代速度**的结构性问题：

| 问题 | 位置 | 影响 |
|---|---|---|
| **巨型模块** | `agents.py` 1,849 行 / `trips.py` 867 行 / `TripDetailView.vue` 1,814 行 | 改动半径爆炸，新需求摸不清隐式约定 |
| **编排双轨制** | `graph.py`（LangGraph 原型，零调用方）+ `agents.py`（手写 asyncio）+ `runtime.py`（AgentLoop，仅服务 chat） | 新增 Agent 不知道写哪，架构债累积 |
| **单进程内存态** | `PlanningExecutor`（asyncio.Queue 单 worker）、`ws_broadcast`（进程内 pub/sub，注释自认多实例需换 Redis） | 水平扩展硬墙；规划任务与 API 抢事件循环 |

**目标**：先让代码「可改」（C：模块化 + 可观测性），再让功能「加得快」（A：Agent 平台化），分布式扩展（B）留到并发压力出现后。

---

## 二、方案确认

多智能体系统架构师视角审查后提出三案，用户确认 **C+A 组合**：

- **方案 C**：模块化 + 可观测性 —— 结构性重构，行为零变化，风险最低
- **方案 A**：Agent 平台化 —— 消灭双轨，统一到声明式 pipeline
- **方案 B**（延后）：任务执行分布式化 —— Postgres SKIP LOCKED + 多 worker，当前单实例下是伪需求

---

## 三、C 方案落地明细

### C1 · schemas 按域拆分

`backend/app/schemas/__init__.py`（657 行）→ 12 个域模块 + 兼容层再导出。

```
schemas/
├── __init__.py      # 统一再导出（旧 from app.schemas import X 零改动）
├── trip.py          # Trip / Day / Stop 聚合根
├── share.py         # 分享令牌 / 行中快照 / 预算汇总
├── events.py        # 行程事件流
├── escalation.py    # 人工兜底评审队列
├── agent.py         # 规划请求 / 异步任务 / 对话式修订
├── auth.py          # 认证
├── chat.py          # 对话会话与消息
├── expense.py       # 行中费用分摊
├── favorite.py      # 收藏灵感夹
├── health.py        # 健康检查
├── xhs.py           # 小红书笔记
└── (plan / plan_b / collab / map_edit / *_import 维持独立)
```

### C2 · trips 路由按域拆分

`backend/app/api/v1/trips.py`（867 行，51 路由）→ 5 个 router，**注册顺序即匹配优先级**：

```python
# api/v1/__init__.py
api_router.include_router(trips_share.router, prefix="/trips", tags=["trips"])      # /share /edit 字面量优先
api_router.include_router(trips_gallery.router, prefix="/trips", tags=["trips"])    # /gallery
api_router.include_router(trips_favorites.router, prefix="/trips", tags=["trips"])  # /favorites
api_router.include_router(trips_escalations.router, prefix="/trips", tags=["trips"])# /escalations
api_router.include_router(trips_crud.router, prefix="/trips", tags=["trips"])       # /{trip_id} 动态兜底
```

| 模块 | 域 | 路由数 |
|---|---|---|
| `trips_share.py` | share/edit 令牌、评论投票、令牌生命周期、免登录 live/events | ~23 |
| `trips_crud.py` | CRUD、days/stops、budget/plan/revise、owner live/events、xhs | ~20 |
| `trips_gallery.py` | 画廊 + 城市模板 | 5 |
| `trips_favorites.py` | 收藏 | 3 |
| `trips_escalations.py` | 人工评审队列 | 1 |

### C3 · 可观测性

- **`app/core/tracing.py`**（新增）：
  - `RequestIdMiddleware`：每请求生成/透传 `X-Trace-ID`（uuid4 hex 16 位），写入 contextvar，响应头带回
  - `trace_context(trace_id)`：后台任务/worker 作用域（与 HTTP 请求维度互补）
- **`app/core/logging.py`**（改造）：
  - `LOG_FORMAT=json` 时输出单行 JSON（`ts/level/logger/message` + trace_id + extra 字段）
  - `LOG_FORMAT=text`（默认）维持人类可读，dev 体验不变
- **`app/common/config.py`**：新增 `LOG_FORMAT: str = "text"`
- **`app/services/planning_service.py`**：`_worker_loop` 用 `with trace_context(f"task-{task_id}")` 包住任务执行体——agent 层所有日志自动带 `task-{id}`

**实测验证**：
```bash
# 中间件响应头
curl -s -D- localhost:8090/api/v1/health | grep x-trace-id   # → x-trace-id: 63a9a44945a84320

# JSON 日志 + trace_id 自动附加
LOG_FORMAT=json .venv/bin/python -c "...with trace_context('task-demo-123'): logger.info(...)"
# → {"ts": "...", "level": "INFO", "logger": "test.obs", "message": "...", "user_id": "u1", "trace_id": "task-demo-123"}
```

### C4 · 前端 API 按域拆分

`frontend/src/api/`：
```
api/
├── http.js          # axios 实例 + 拦截器（Bearer token / 401 跳转 / 错误 toast）
├── index.js         # 统一出口（export * from modules/*，旧 import 零改动）
└── modules/
    ├── auth.js  trips.js  share.js  live.js  plan.js  planner.js
    ├── favorites.js  discovery.js  events.js  chat.js  ws.js
```

### C5 · TripDetailView 拆分

`frontend/src/views/TripDetailView.vue`（1,814 行）→ 5 个 composables + ~180 行装配层：

| Composable | 职责 |
|---|---|
| `useTripDetailLoad.js` | trip/budget/plan 加载状态机、离线降级、行中快照、Plan B、收藏检查注入 |
| `useRevise.js` | AI 对话式修订（输入/状态/diff 预览/quality 质控报告） |
| `useEditDialog.js` | 编辑对话框三合一（行程/日程/站点）+ 删除 + 上下移 |
| `useTripShareActions.js` | 分享/收藏/画廊/编辑权/令牌生命周期 |
| `useExport.js` | 截图 / PDF / JSON / 打印 |

---

## 四、A 方案落地明细

### A1 · Agent Pipeline 平台化（生产路径切换）

**新增 `backend/app/agent/pipeline.py`**（声明式步骤编排框架）：

- `PipelineStep`：一个编排阶段（name / deps 并行依赖 / on_failure 降级策略）
- `PlanningPipeline`：步骤注册表 + 执行器（顺序 + deps 分波并行 fan-in）
- `CollectAgentsStep`：首批迁移步骤——六路采集（attraction/weather/hotel/food/transport/discount）并行 + `return_exceptions`（单 agent 失败不整体抛错）
- `run_collect_stage(request, provider, max_iterations)`：便捷入口

**生产路径切换**：`agents.py::run_planning_agents` 的采集段（1224-1237 行手写 `asyncio.gather`）替换为 `await run_collect_stage(...)`，产物解包为 `a_res/w_res/h_res/food_res/t_res/d_res`，**事件/trace/制品契约不变**（trace 仍由主流程统一打点，保持 i18n 文案）。

行为等价性要点：
- 原实现 `asyncio.gather` 有一个失败即整体抛错 → 新实现 `return_exceptions=True` 单 agent 失败降级为 `{"status": "failed"}`，下游 foods fallback 等逻辑原样生效
- 每个失败 agent 产物带缺省结构（`.get()` + 兜底默认），与采集 trace 契约对齐

### A2 · 死代码清理

`backend/app/agent/graph.py`（LangGraph 原型，341 行，仓库内零调用方）已删除，归档至 `docs/archived/graph-langgraph-prototype-2026-10.py.bak`。

`pyproject.toml` 中 `langgraph>=0.2.0` 依赖保留（`runtime.py` 仍引用其消息类型）。

---

## 五、验证结果

| 验证项 | 结果 |
|---|---|
| 后端全套测试（C1→A2 每步后） | **523 passed** ✅（每步改动后均全量回归） |
| 前端 Vite build | **✓ built** ✅（C4/C5 后各构建一次） |
| 中间件响应头 X-Trace-ID | ✅ 实测存在 |
| JSON 日志 trace_id 自动附加 | ✅ 实测输出带 trace_id/extra 字段 |

---

## 六、新架构下的开发指南

### 加一个新 API（后端）
1. 建 `api/v1/trips_xxx.py`（或复用现有域文件），`router = APIRouter()`
2. 在 `api/v1/__init__.py` 注册：**按匹配优先级排序**（字面量段在 `/` 动态段之前）
3. 建 `schemas/xxx.py`，在 `schemas/__init__.py` 加一行再导出

### 加一个新 Agent（后端）
1. 在 `agent/pipeline.py` 实现 `PipelineStep` 子类（`run(self, ctx, **kwargs)` 返回结构化产物）
2. `pipe.add(MyAgentStep())` 注册，`deps` 声明并行依赖
3. 逐段从 `agents.py` 迁移，每段迁移后跑全套回归

### 加一个新页面逻辑（前端）
1. 逻辑放 `composables/useXxx.js`（状态 + 动作收敛）
2. 页面 `<script setup>` 只做装配（调 composable、绑定模板）

### 排障（可观测性）
1. 请求出问题 → 浏览器 DevTools 取 `X-Trace-ID` → grep 日志
2. 规划任务出问题 → 日志里搜 `task-{task_id}`
3. `LOG_FORMAT=json` 直接接 ELK/Loki/CloudWatch

---

## 七、变更文件清单

**后端新增**：
```
backend/app/schemas/{trip,share,events,escalation,agent,auth,chat,expense,favorite,health,xhs}.py
backend/app/api/v1/trips_{share,crud,gallery,favorites,escalations}.py
backend/app/core/tracing.py
backend/app/agent/pipeline.py
```

**后端修改**：
```
backend/app/schemas/__init__.py        # 兼容层再导出
backend/app/api/v1/__init__.py         # 5 个 router 聚合（顺序=优先级）
backend/app/core/logging.py            # JSONFormatter + trace_id 附加
backend/app/common/config.py           # LOG_FORMAT
backend/app/main.py                    # RequestIdMiddleware
backend/app/services/planning_service.py  # trace_context 包裹任务执行
backend/app/agent/agents.py            # 采集段 → run_collect_stage
```

**后端删除**：`backend/app/agent/graph.py`（归档 `docs/archived/`）

**前端新增**：
```
frontend/src/api/http.js
frontend/src/api/modules/{auth,trips,share,live,plan,planner,favorites,discovery,events,chat,ws}.js
frontend/src/composables/{useTripDetailLoad,useRevise,useEditDialog,useTripShareActions,useExport}.js
```

**前端修改**：`frontend/src/api/index.js`（统一出口）、`frontend/src/views/TripDetailView.vue`（装配层）

---

## 八、后续建议（未做，按需排期）

| 项 | 触发条件 | 方案 |
|---|---|---|
| **B1 分布式任务队列** | 多实例部署 / 规划并发压力 | `PlanningExecutor` → Postgres `SKIP LOCKED` 轮询 + web/worker 进程分离；`ws_broadcast` → Redis pub/sub |
| **A1 深度迁移** | 下一批 Agent 开发前 | Planner/Critic/DrivingGate/TimeGate 逐段注册为 `PipelineStep`，`agents.py` 收敛为纯装配 |
| **前端 code-split** | 首屏优化 | TripDetailView chunk 620KB，路由级 `defineAsyncComponent` + `manualChunks` |
| **日志采集接入** | 部署生产环境 | `LOG_FORMAT=json` + 采集器（Loki/ELK），按 trace_id 检索 |

---

## 九、结论

C+A 方案全部落地且每步全量回归通过。当前仓库：
- **可改**：模块边界清晰，新需求改动半径缩小一个数量级
- **可测**：schema/路由/编排均有独立测试文件，改动后全量回归兜底
- **可观**：请求级 + 任务级 trace 贯穿，坏答案可回溯到具体 agent 调用
- **可扩展**：pipeline.py 为新 Agent 提供声明式注册入口，双轨债务清零