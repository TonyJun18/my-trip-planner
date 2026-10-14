# 评估记录 · task-guest-trial 免登录试用规划（候选评估）

> 任务来源：docs/night-build-todo.md（2026-10-09 竞品分析追加项，2026-10-15 竞品分析行动项④再次确认排队）
> 评估日期：2026-10-15（夜间流水线 worker #2）
> 结论：**评估不过 → 记录降级，关单**（不做 guest 建行程；后续条件成熟可另立 phase2）

## 1. 任务背景与验收标准

任务原文：「Wonderplan 免费无门槛 / Mindtrip 免 signup 30 秒出行程；我们创建需登录、分享页 token 免登录仅消费端。先评估 guest 数据安全 / 成本滥用 / 与 share_token 语义边界，评估不过则仅记录降级。」

验收：「评估记录 +（若通过）guest 建行程 / 注册接管 / 提示文案 / 测试覆盖；评估不过则仅记录降级并关单」。

## 2. 竞品事实（2026-10-15 竞品分析已抓取）

| 竞品 | 免登录程度 | 代价 / 短板 |
|---|---|---|
| Wonderplan | 完全免费无门槛 | 模板生成器：换预算/人群档位常得到同一底稿重排；单城市、无协作、无多语言。免费低摩擦是唯一护城河，质量公认差 |
| Mindtrip | 需 signup（宣传「免 signup 30 秒出行程」实测需 Google 账号落地） | 靠 1100 万 POI 库 + chat 预订支撑留存，登录换取画像/主动提醒/协作 |
| Google Canvas | 零注册 | 绑定 Google 生态（地图/预订/日历），巨头生态内玩法，独立工具无法复制 |

共同规律：**免费无门槛本身不构成留存；留存靠「登录后」的深度（画像/协作/预订/提醒）**。Wonderplan 是无深度免费的活反例，其短板正是我们的差异化所在（四维质检/修订闭环/诚实预算/画像记忆）。

## 3. 现状盘点（代码事实，2026-10-15 核验）

- **创建端全部登录**：前端 `router.beforeEach` 除 `/login` 外全部重定向登录；后端 `POST /api/v1/trips`（trips.py:383）与规划端点全部依赖 `get_current_user`（core/auth.py，Bearer JWT）。
- **已存在免登录消费端**：`share_token` 只读（GET /trips/share/{token}）、评论、投票、`edit_token` 受邀编辑、live 今日视图快照——语义均为「已登录用户创建的行程，持令牌免登录消费」。
- **数据模型**：`Trip.owner` 列 nullable=True（models/trip.py:40），但归属校验 `trip_service._load_trip(db, trip_id, owner=owner)` 与 `get_plan(owner=...)` 全链路假设「有主」；`share_lifecycle` 令牌生命周期、`collab_service._voter_key`（token+IP+UA 匿名身份）都是消费端机制。
- **成本结构**：规划 = 多 agent LLM 流水线（PlannerAgent/Attraction/Hotel/Food/Transport/Weather 等，`invoke_with_resilience` 多轮 LLM 调用，provider 可切 deepseek/openai），一次规划消耗多轮 LLM token；`planning_service` 用 asyncio 单 worker 队列防并发打爆，但**无任何按 IP/账号的限流设施**（全仓 grep rate_limit/throttle/limiter 无命中），LLM 成本熔断（LLM_BREAKER_*）防的是系统性故障，不是防恶意刷单。
- **无 guest 先例**：代码与 docs 均无 guest 机制（仅 landing-page-proposal.md 第 4 条提过「无先尝后买」的产品缺口提案，未立项）。

## 4. 评估：三条维度逐一裁决

### 4.1 成本滥用 —— ❌ 不通过（阻断级）

- guest 免登录创建行程 = 脚本可循环调用 `POST /trips` + 规划端点，每次消耗多轮 LLM token；LLM 供应商按量计费，**匿名端点等于给全网开免费算力矿场**。
- 当前零限流设施：要做 guest 必须先建「IP 限流中间件 + 每 IP 配额 + 熔断告警」整套新基础设施。这是独立工程（涉及中间件/配额表/运维告警），不是「最小版 guest 功能」的附属品。
- 注册登录用户已有天然配额锚点（user_id），guest 没有；为 guest 单独建配额体系，性价比低于直接引导注册（Google OAuth 一键）。

### 4.2 数据安全与孤儿数据 —— ❌ 不通过

- guest 行程 owner=NULL：`_load_trip` 归属校验、`get_plan(owner=...)`、`share_lifecycle`、删除/权限链路全部假设有主；owner=NULL 行程需要一条「仅凭 guest_token 可读写」的旁路访问控制，与现有 JWT 双轨并存，权限模型复杂度暴涨（最小权限原则要求每增加一条旁路就要重新审计整条信任链）。
- 孤儿数据治理：guest 行程无主、无找回，需要「24h 自动过期 + 容量上限 + 定时清理」配套，否则 DB 被无主行程灌满；清理任务本身又是新流水线。
- 注册接管（guest 行程 → 登录用户认领）：需「认领 token」防越权接管（A 的 guest 行程不能让 B 认领），连带 plan/days/stops/share 记录归属迁移——高风险改动，出错即数据串号。

### 4.3 与 share_token 语义边界 —— ❌ 边界清晰但会放大复杂度

- share_token = 「有主行程的免登录消费」。它与 guest 创建不冲突，但也**不提供任何可复用件**：share 侧校验的是「令牌→行程」映射，guest 侧需要的是「匿名→可写会话」映射，凭据体系、生命周期、撤销机制全部要新做。
- 把 guest 塞进 share 语义会污染令牌信任模型（share 令牌假定「行程已存在且有主」，guest 打破该假定），违反「最小权限 / 信任边界清晰」原则。

### 4.4 产品价值 —— 🟡 低

- 我们留存支柱=画像记忆（preference_service 行为记忆推断）+ 协作 + 修订闭环，全部依赖登录身份；guest 试玩无法沉淀画像，「试玩即弃」对转化帮助有限。
- 起点摩擦已通过 task-inspiration-mode（灵感入口：预算档/兴趣/季节 → 目的地卡片 → 预填）大幅降低，登录仍只需 Google OAuth 一键；Wonderplan 式「免费无门槛」恰恰把我们推向「模板化廉价感」，与「四维质检/诚实标注」定位相悖。
- 10-15 竞品分析结论同向：「免费体验 + 独有深度」（行动项 3 文章论述），而非「免费无深度」。

## 5. 结论与降级方案

**结论：评估不过，按验收标准「仅记录降级并关单」。** task-guest-trial 关闭，不进入 todo 实施队列。

**降级替代（已存在或已排队，零新凭证）**：
1. **灵感模式**（task-inspiration-mode ✅ 已完成入 main 待合并）：起点摩擦从「填表单」降到「选卡片」，就是我们的「免登录级低摩擦」替代。
2. **Google OAuth 一键登录**（已有）：登录摩擦≈免登录。
3. **分享页免登录消费**（已有）：share_token 只读/投票/受邀编辑，覆盖「给别人看」场景。

**若未来重启（phase2 前置条件，需用户决策立项）**：
1. IP + 账号双层限流（每 IP 每日 N 次 guest 规划，配额表 + 告警）；
2. guest 行程 24h 过期 + 容量上限 + 定时清理任务；
3. 注册接管走显式 claim token（防越权认领）；
4. guest 规划触发页提示「注册后保存与协作」文案。
以上任一实现均为独立任务（估 backend 大规模 + ops），不建议在夜间单窗口内仓促实施。

## 6. 验收对照

| 验收项 | 状态 |
|---|---|
| 评估记录 | ✅ 本文档 |
| （若通过）guest 建行程/注册接管/提示文案/测试覆盖 | — 评估不过，不适用 |
| 仅记录降级并关单 | ✅ todo 勾选 [x] + 本记录 + checkpoint 关单 |