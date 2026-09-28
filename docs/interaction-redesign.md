# 旅行规划交互重设计

> 目标:从「1 轮表单 + 黑盒 Agent + 事后修订」改为「可观察的多阶段规划 + 结果审阅工作台 + 多轮对话纠错」。
> 范围:1 期 = 分段透明化(阶段视图 + 中间制品可见)+ 审阅工作台(对话修订 + 手动微调);2 期 = 检查点门控(C)。
> 状态:已评审,实施中。

---

## 1. 现状诊断

### 1.1 当前流程

```
表单(固定 4 题 QA)
  → POST /planner/plan(异步任务)
  → 轮询 /planner/tasks/{id}(或 WS /ws/planner/tasks/{id})
  → 规划中只展示裸 trace(agent 名 + action + observation 技术日志)
  → 完成即落库 Trip
  → 结果页「查看详情」;不满意 → 去详情页单条 revise 输入框
```

### 1.2 痛点

| # | 痛点 | 根因 |
|---|------|------|
| P1 | 交互差:一次性表单,缺信息只能靠写死的 4 题 | 无动态追问;表单是唯一入口 |
| P2 | 黑盒:规划中只能看技术日志,看不懂、插不进手 | trace 是 T-A-O 执行记录,不是用户可读的阶段/产物 |
| P3 | 1 轮对话:提交后到出结果前无法干预 | 任务无门控点,中间产物不持久化 |
| P4 | 结果不可审:完成即落库,结果页无修订能力 | revise 只在详情页;结果页只是展示 |

### 1.3 现有资产(可复用)

- WS 实时事件链:agents → callback → hub.publish(`planner:{task_id}`) → ws 端点推送(含快照)
- `run_planning_agents`:采集(景点/天气/酒店/餐厅)→ Planner → Critic(evaluator-optimizer)→ DrivingGate → plan
- `revise_trip`:PlanReviseAgent 出结构化 diff,代码原子应用 + 预算重算 + DrivingGate;返回计划 + 人类可读 diff 摘要
- `Trip` / `TripDay` / `Stop` CRUD + reorder 接口;`TripPlan` 快照

---

## 2. 方案对比与决策

| 方案 | 交互 | 黑盒 | 实时纠错 | 工作量 | 风险 |
|------|------|------|----------|--------|------|
| A 全程对话 | 最彻底 | 对话流卡片 | 全程 | 大 | 上下文预算失控 |
| B 分段透明 + 审阅工作台 | 中 | 看得见 | 产出后 | 中 | 规划中仍不能介入 |
| C 检查点门控 | 高 | 看得见+能决定 | 3 个决策点 | 大 | 打断次数多 |
| B + 预留 C 状态机 | 中 | 看得见 | 产出后(1 期) | **中(选定)** | 低 |

**决策**:1 期做 B(快速见效、风险低),同时把 `PlanTask` 状态机按 C 的形状预留(`state` 字段 + 事件契约),2 期即插门控。

---

## 3. 目标交互(1 期)

### 3.1 规划中:阶段状态机(替代裸 trace)

```
🔍 资料收集 [running]
   · 景点 12 项 ✓  天气 3 天 ✓  酒店 5 项 ⏳  餐厅 4 项 ✓
   ▸ 展开:候选清单 chips(名称 + 花费 + 时长)
🧠 行程编排 [pending/running/completed]
   · 3 天草案生成 ✓
   ▸ 展开:按日主题列表
✅ AI 质检 [pending/running/completed]
   · 评分 92/100 · 2 个提示
   ▸ 展开:问题列表
```

- 每个阶段有 `running / completed` 状态,产出以「制品卡片」呈现,可展开看明细
- 无 events 时(旧任务/降级)回退渲染原 trace 列表

### 3.2 结果:审阅工作台(替代只读结果页)

```
┌─ 成果横幅(目的地 · N 天 · 预算)─────────────┐
│  逐日卡片(数据源 = 已落库 Trip,含 id)          │
│    Day 1 · 日期 · 主题                         │
│      1. 西湖        ¥0   2h  [↑][↓][🗑]      │
│      2. 楼外楼      ¥200 1.5h [↑][↓][🗑]      │
│  ────────────────────────────────────────  │
│  [对话修订输入框: 「D2 太赶,去掉灵隐寺」] [发送] │
│  变更历史: 14:02 已把第三天调整为…  ⟵ 时间线    │
└──────────────────────────────────────────┘
  手动微调:删站(二次确认)/ 上移下移(整日重排)
  对话修订:复用 POST /trips/{id}/revise(原子 diff + 预算重算)
```

- 数据源切换:结果区使用 `GET /trips/{id}`(带 day/stop id)→ 手动微调可落库
- 修订后重新拉取 trip + push 变更历史条目;plan 特有信息(quality/hotels)仍来自 result.plan

---

## 4. 事件契约(agents → 前端)

规划过程中,agents 层按序发出以下事件(均带 `task_id`,经 WS 推送,并**持久化到 `plan_tasks.events`** 供轮询/快照读取):

```jsonc
// 阶段状态
{ "type": "phase",   "phase": "collecting",  "status": "running" }
{ "type": "phase",   "phase": "collecting",  "status": "completed",
  "summary": "景点 12 · 天气 3 天 · 酒店 5 · 餐厅 4" }

// 中间制品(轻量摘要;完整数据分别走 plan / quality 字段落库)
{ "type": "artifact", "artifact": "attractions",
  "data": [{ "name": "西湖", "type": "attraction", "estimated_cost": 0, "duration_minutes": 120 }, ...] }
{ "type": "artifact", "artifact": "weather",
  "data": [{ "date": "2026-09-26", "text_day": "晴", "temp_max": 28, "temp_min": 19 }, ...] }
{ "type": "artifact", "artifact": "hotels",
  "data": [{ "name": "西湖大酒店", "estimated_cost": 500, "rating": 4.5 }, ...] }
{ "type": "artifact", "artifact": "foods",
  "data": [{ "name": "楼外楼", "type": "food" }, ...] }
{ "type": "artifact", "artifact": "draft",
  "data": { "days": 3, "themes": ["西湖经典", "灵隐禅意", "运河人家"] } }
{ "type": "artifact", "artifact": "quality",
  "data": { "score": 92, "passed": true, "rounds": 1, "max_rounds": 2,
            "finalized": false, "issues": [{ "severity": "info", "category": "info", "message": "..." }] } }
```

- `phase`:collecting → assembling → reviewing(预留 2 期:collecting 可挂 `awaiting_review(candidates)` 门控)
- 数据裁剪原则:events 只存展示所需字段,避免 PlanTask 行膨胀;全量数据仍走 `plan` / `trace` 列
- 事件持久化失败不影响主流程(推送链已有容错)

---

## 5. 数据模型与接口变更

### 5.1 `plan_tasks` 表(迁移)

```python
# 新增列
events: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 阶段/制品事件流(轮询可读)
state:  Mapped[str | None] = mapped_column(String(20), nullable=True)  # 2期预留:collecting/awaiting_review/assembling/reviewing/completed
```

- `state` 本期仅写 `collecting/assembling/reviewing/completed`(不回写 waiting),为 C 的 `awaiting_review(...)` 预留
- 事件写入:callback 链中串行(RMW + 锁),独立 session,失败静默

### 5.2 API

- `GET /planner/tasks/{id}` → `PlanTaskOut` 增加 `events: list | None`、`state: str | None`
- `WS /ws/planner/tasks/{id}` 快照同样带 `events` / `state`
- 无新端点(2 期再加 `POST /planner/tasks/{id}/gate`)

---

## 6. 故障设计

| 故障 | 行为 |
|------|------|
| 事件持久化失败 | 静默;前端 WS 仍实时,轮询退化为旧 trace 视图 |
| 采集某一项失败(如餐厅) | 既有降级:跳过后继续;阶段 summary 标注失败项 |
| revise 失败 | 复用现有 4xx(diff 解析/应用失败),前端提示、不丢本地状态 |
| reviser 返回空 diff | 提示「未检测到变更」 |
| 任务超时/失败 | 既有状态机标记 failed;阶段视图显示失败阶段 |

### 7. 2 期(C)预留点

- `PlanTask.state` 增加 `awaiting_review`(`gate` 字段:候选 JSON + 超时时间)
- 新端点 `POST /planner/tasks/{id}/gate`(提交门控决策;幂等;超时自动默认通过)
- worker 在门控点暂停 + 持久化中间状态;`planning_service` 增加恢复扫描
- 前端看板在 `awaiting_review` 渲染候选确认卡

---

## 8. 实施计划

| 步骤 | 内容 | 文件 |
|------|------|------|
| 1 | agents 层发 phase/artifact 事件 | `backend/app/agent/agents.py` |
| 2 | PlanTask 加 events/state + 迁移;事件桥落库 | `backend/app/models/trip.py`, `app/services/planning_service.py`, `backend/alembic/versions/` |
| 3 | PlanTaskOut / ws 快照带 events+state | `backend/app/schemas/__init__.py`, `backend/app/api/v1/ws.py` |
| 4 | 前端阶段视图(规划中) | `frontend/src/views/PlanWizard.vue`, `locales/*` |
| 5 | 前端审阅工作台(结果区) | 同上 |
| 6 | 后端 pytest + 前端 build 验收 | — |