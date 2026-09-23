# 表单、对话、地图拖拽：三种行程修订范式的工程代价

> 本文是 my-trip-planner 内容沉淀系列第 05 篇，为 `task-map-drag-edit`（地图拖拽修订）铺路的定位文章。
> 目标读者：协作者 / 潜在贡献者 / 技术决策者。所有代码引用均以本仓库当前实现为准（2026-09-24 核对）。

## TL;DR

行程（itinerary）修订是 AI 旅行工具的"最后一公里"：生成一份行程很容易，让用户在三天后仍能按自己的意志修改它很难。我们观测到三种主流修订范式：

1. **表单编辑（Form）**——精确、可校验、颗粒度细，但认知负担重；
2. **对话修订（Conversation）**——自然、低门槛，但用户对"AI 会怎么改"缺乏确定感；
3. **地图拖拽（Map Drag）**——与空间直觉最匹配，但工程代价最高。

本文对比三种范式的**体验收益**与**工程代价**，并说明我们的选择：以"AI 生成 diff + 代码原子应用"为核心，表单与对话为两翼，地图拖拽作为下一步演进目标。

## 1. 为什么"修订"是 AI 行程工具的一等公民

生成一次行程是单发任务：输入偏好 → 模型推理 → 输出结构化方案。修订则是**多轮、高频率、强确定感需求**的任务：

- 用户看完生成结果，几乎必然要改（预算、同行人、天气、临时事件）；
- 修订是"回写既定事实"——用户的意志要能**确定地**反映到行程里；
- 修订失败的成本比生成失败更高：用户已经建立心理预期，改不动 = 工具不可信。

`content-diff-positioning`（04 篇）已论证"修订"是差异化定位。本文聚焦**修订用什么交互范式实现**，以及每种范式在生产上要付出什么。

## 2. 三种范式与工程代价

### 2.1 表单编辑（Form）

**体验**：打开站点卡片，编辑名称/类型/坐标/时长/预算字段，点保存；用上移/下移或拖拽调顺序。

**工程代价：低-中**。典型实现：

- CRUD API（`POST /days/{day_id}/stops` 添加站点、`PATCH /days/{day_id}/stops/{stop_id}` 编辑站点、`DELETE /days/{day_id}/stops/{stop_id}` 删除站点、`PUT /days/{day_id}/stops/order` 重排整日站点顺序——均位于 `backend/app/api/v1/trips.py`）；
- 前端受控表单 + 校验（必填、数值范围、类型枚举）；
- 需要处理"半途放弃"（脏状态、取消还原）、"并发冲突"（他人已改）、"联动重算"（改预算 → 总预算、改时长 → 当日总时长）。

**我们仓库现状**：`TripDetailView.vue` 已实现站点编辑对话框（`openEditStop` → `saveEditStop`）、整点上移/下移按钮（`moveStop` → `api.reorderStops(day.id, order)`）。表单编辑的 CRUD 基础已存在，但依赖用户逐字段理解（"estimated_cost"是什么单位？duration 是否含通勤？）。

**短板**：精确但**慢**；用户必须知道"哪个字段、什么值"，而不是"我想把第三天弄松一点"。

### 2.2 对话修订（Conversation / AI diff）

**体验**：用户在输入框写一句自然语言："第三天太赶了，西湖只留半天，晚上想吃楼外楼"，AI 返回结构化变更预览，确认后原子应用。

**工程代价：高（但收益也最高）**。这是我们当前的主路径（方案 B）：

- **AI 只生成 diff，代码执行**：`app/services/revise_service.py` 中 `plan_revise_agent` 输出 `ReviseDiff`（`actions[]`：`replace/add/remove/reorder`），随后 `_apply_diff` 逐条校验并应用。AI 永远不直接落库——延续"LLM 只做理解，代码做执行"的项目哲学；
- **原子性**：`_apply_diff` 先做完整合法性检查（定位 day/stop、字段白名单、index 范围），全部通过才写入；任一动作非法 → 抛 `AppError`，service 不 commit → 事务整体回滚。用户不会看到"改了 3 条，第 4 条失败"的脏状态；
- **约束门**：修订后 `_enforce_driving_constraints` 用 `driving_service.check_plan_driving` 做确定性校验（超距/超时 → 整体拒绝，`revise_driving_violation`）——AI 想加一个远距站点也无法静默落库；
- **预算重算**：`_recompute_budget` 由代码（`compute_budget`）重算预算并写回 plan 快照，LLM 估值不可信；
- **可观测**：响应带 `trace`（AgentTraceStep 规范化）与 `diff` 人类可读预览（`op_label`/`target_name`/`day_number`/`fields`），前端 `TripDetailView.vue` 的 `diffText` 渲染成"Day3 · 修改「西湖」（name、duration_minutes）"这类文案；
- **schema 契约**：`ReviseAction` 是严格 `Literal` 枚举 + `extra="ignore"`，非法 op 直接报 `revise_bad_op`。

**短板**：
- **确定性依赖**：AI 对"用户意图 → 结构化 diff"的解析质量决定体验，失败路径（`revise_parse_failed`）仍需用户换措辞；
- **diff 预览的粒度**：用户看到的是"修改了哪个站点哪些字段"，不是"地图上这个点挪到这里"的空间直觉；
- **上下文成本**：对话修订需要把当前行程快照（`_plan_snapshot`）喂给 agent，行程越长 token 越高。

### 2.3 地图拖拽（Map Drag）

**体验**：在地图上直接拖动站点标记改位置，拖完后路线折线实时更新；支持按日着色、聚类。

**工程代价：高**。这是**尚未实现**的方向（`docs/night-build-todo.md` 的 `task-map-drag-edit`），估算代价来自我们已有代码基础：

- **地图交互层**：当前 `TripMap.vue` 基于 Leaflet 只读渲染（markers + polyline，divIcon 自定义序号）。拖拽需要：marker drag 事件 → 坐标回写 → 防抖保存 → 撤销栈。**坐标是唯一直接可拖的字段**（lat/lng），但行程修订大多不是"改坐标"而是"改顺序/增删/改时长"——地图拖拽天然只覆盖 `reorder` + `replace(lat,lng)` 两个 op；
- **顺序与地图的映射**：地图上没有"第几位"的天然语义；把"拖动 marker"翻译成 `reorder` 需要额外启发（按拖后位置重排该日 stops 并重新编号 `order_index`）；
- **约束联动**：拖动导致超距/超时 → 必须即时反馈（不能只靠保存时报错）；这需要把 `check_plan_driving` 前置到前端交互或提供轻量校验端点；
- **预算/时长联动**：改坐标通常不影响预算，但改顺序影响路线总里程 → driving 报告需联动刷新；
- **移动端**：拖拽手感在触屏上远差于桌面；需要退化为"长按排序"或保留表单/对话作为兜底。

**结论**：地图拖拽是**最高表达力、最高工程代价**的范式。它不是替代对话修订，而是补充**空间直觉**这一个维度。

## 3. 功能矩阵（范式 × 维度）

| 维度 | 表单编辑 | 对话修订（我们已实现） | 地图拖拽（待做） |
|---|---|---|---|
| 表达力（改什么） | 精确字段 | 自然语言任意意图 | 空间位置/顺序 |
| 用户认知负担 | 中（要懂字段） | 低（说人话） | 低（拖就完了） |
| 确定感（改完会怎样） | 高（所见即所得） | 中（依赖 diff 预览） | 高（所见即所得） |
| 工程代价 | 低-中 | 高 | 最高 |
| 错误处理 | 表单校验 | 原子性 + 约束门 | 需防抖 + 约束前置 |
| 移动端 | 好 | 好 | 差（退化方案） |
| 与 AI 的协同 | 弱（纯手工） | 强（AI 出指令） | 弱-中（可做快照对比） |

## 4. 范式组合策略：以 diff 为核心的统一修订内核

我们当前架构的隐藏优势：**三种范式共用同一个 `ReviseDiff` 内核**。

- 表单编辑 → 前端把表单变更序列化成 `{op:'replace', day_number, target, fields}`，走同一个 `_apply_diff`；
- 对话修订 → AI 生成 `ReviseDiff`，走同一个 `_apply_diff`；
- 地图拖拽 → 前端把拖拽结果序列化成 `{op:'reorder', ...}` 或 `{op:'replace', fields:{lat,lng}}`，走同一个 `_apply_diff`。

即：**交互范式可以更换，修订内核不变**。这大幅降低"新增一种修订方式"的边际成本，也保证所有路径共享原子性、约束门与预算重算。这是我们在路线图上安排 `task-map-drag-edit` 的底气——它不需要重写修订服务，只需要新增一个"地图 → diff"的翻译层。

## 5. 对 task-map-drag-edit 的建议（作为下步铺垫）

1. **范围收窄**：第一版只支持"拖动 marker 改 lat/lng + 按拖后顺序生成 reorder"，不做日区间拖拽；
2. **约束前置**：拖动过程中用轻量校验（可复用 `check_plan_driving` 的确定性逻辑）即时提示"该调整将使当日车程超时"；
3. **统一 diff**：前端把拖拽翻译成 `ReviseDiff` 调现有 revise 端点，完整复用原子应用与预算/自驾重算；
4. **移动端退化**：拖拽在触屏隐藏，保留表单与对话修订入口。

## 6. 相关代码索引（仓库现状核对）

- 修订服务：`backend/app/services/revise_service.py`
- 修订 schema（`ReviseAction`/`ReviseDiff`）：`backend/app/schemas/__init__.py`
- 修订 API：`backend/app/api/v1/trips.py`（`POST /{trip_id}/revise`）
- 前端对话修订 + 表单编辑 + 上移/下移：`frontend/src/views/TripDetailView.vue`
- 地图（只读）：`frontend/src/components/TripMap.vue`
- 自驾确定性校验：`backend/app/services/driving_service.py`

---

*写于 2026-09-24 夜间流水线。本文为内容沉淀，不新增功能代码；引用实现均已在 main 分支合并（`nightly/2026-09-24/2-task-share-edit` 等分支并入后）。*