# 产品需求文档（PRD）：智能旅行助手 my-trip-planner

**Status**: In Development（功能梳理版）  
**Author**: Alex (PM)  **Last Updated**: 2026-09-25  **Version**: 1.0  
**Stakeholders**: Eng Lead / Design / Marketing  
**关联文档**: `README.md` · `docs/articles/`（技术沉淀） · `docs/night-build-todo.md`（迭代任务源）

> 本 PRD 是对**现有系统**的功能梳理（反向文档化），所有功能均以代码实现为准，
> 验收要点提炼自实际路由、服务与测试行为。

---

## 1. Problem Statement（问题陈述）

### 1.1 我们在解决什么

大众旅行者在规划一次出行时面对的核心痛点：
- 多平台信息割裂（景点 / 酒店 / 天气 / 餐饮分散在 App、攻略、评论区），手工整合成本高；
- LLM 生成行程的常见问题：**输出不可信**（幻觉数据）、**结构不可用**（JSON 解析失败）、
  **质量不可控**（行程不合理但无人把关）、**不可修订**（生成即冻结）。

本项目把"让多个 Agent 稳定、可靠、可测试地产出结构化业务数据"作为核心问题，
而不是"调一个 LLM 生成 JSON"的 demo。

### 1.2 不解决的代价

- 行业现状：AI 旅行工具同质化严重，且正滑向"预订漏斗"（agentic 订票 / OTA 收购）。
- 独立工具的机会在**规划层**：免费、透明、可修订、可协作、可自托管。
- 如果输出不可信 / 不可回溯 / 不可回滚，用户一次糟糕体验即流失，无法建立信任。

### 1.3 差异化定位

> 我们没有 7×24 人工客服（OTA 有定制师/指路人），但我们保证**每一个自动产出都可验证、可回溯、可回滚**。

- 工程化降级链（重试 → 熔断 → provider/数据源兜底 → Critic 降级放行）；
- 可回溯的质检 trace（哪个 Agent、哪一步、哪个校验）；
- 确定性代码兜底（数学与事实交给代码，LLM 只做理解与编排）。

---

## 2. Goals & Success Metrics（目标与成功指标）

| Goal | Metric | Current Baseline（代码现状） | Target | 度量窗口 |
|------|--------|----------------|--------|----------|
| 行程可产出 | AI 规划任务成功率（completed / 总任务） | —（需埋点） | ≥ 90% | 上线后 30 天 |
| 输出可信 | 规划结果通过 Pydantic 强校验率 | 测试覆盖（95 tests） | 100%（失败自纠正 ≤3 次） | 每次规划 |
| 输出质量 | 质检（Critic）四维评分 ≥ 80 分通过率 | — | ≥ 70% | 每次规划 |
| 可修订 | 对话式修订（revise）成功率 | —（Diff 原子应用，任一失败回滚） | ≥ 85% | 上线后 30 天 |
| 协作活跃 | 分享行程被评论 / 投票率 | — | ≥ 10% 的分享行程有互动 | 90 天 |
| 容错 | LLM 故障不阻断主流程（Critic 降级放行率） | 100% 降级路径有代码实现 | 主流程可用性 ≥ 99.9% | 持续 |
| 可测试 | 测试不依赖外部（FakeLLM） | 95 tests / 不耗 token | 保持全离线 | 每次 CI |

---

## 3. Non-Goals（不做的事）

- **不做预订 / 支付闭环**：无分销商 API 对接，用户只拿"计划"不下单（方案 C 未做）。
- **不做真实导航**：自驾校验基于球面距离估算，不接高德路径规划 API（有 key 配额成本）。
- **不做实名账号体系**：分享/协作基于匿名令牌 + 设备指纹，非强认证。
- **不做协商式多 Agent**：编排是管道式（pipeline），非 Agent 间互相讨论（由 plan-then-review 部分弥补）。
- **不做移动端专门优化**：前端面向桌面 Web。
- **多语言覆盖进行中**：en-US 下部分硬编码中文未迁移完（task-i18n-views 完成三大业务视图）。

---

## 4. User Personas & Stories（用户画像与故事）

### Primary Persona
**小刘** — 28 岁城市白领，周末/小长假出游，预算敏感（3k 级），
会用 AI 工具但吃过"AI 编造行程"的亏，重视信息真实与行程可调整。

### Secondary Persona
**同行旅伴 / 出发前协作者** — 拿到分享链接的人，需要评论、投票表达意见，
受邀时可轻量修改站点备注/勾选/顺序，而**不需要注册账号**。

### Stories

**Story 1（AI 规划）**: 作为旅行者，我想要输入目的地/日期/预算/偏好后自动得到完整行程，
以便免去多平台手工整合。
**验收要点**:
- [ ] 提交规划立即返回 task_id（202），前端轮询可看到 4 个 Agent 的 T-A-O 轨迹
- [ ] 景点/酒店来自真实数据源（高德 POI，未配置自动降级 Tavily/Nominatim）
- [ ] 天气走确定性纯工具路径（城市 → wttr.in/高德），零 token、零幻觉
- [ ] Planner 产出经 PlanSchema 强校验，失败自动自纠正（≤3 次）
- [ ] Critic 四维质检（schedule/budget/geography/logistics），≥80 通过，否则重生成（≤2 轮后强制定稿）
- [ ] Critic 自身故障 → 降级"通过放行"，绝不阻断主流程

**Story 2（对话式修订）**: 作为旅行者，我可以用一句话调整行程（"第三天太赶了，西湖留半天"），
以便不推倒重来。
**验收要点**:
- [ ] PlanReviseAgent 把用户请求解析为结构化 diff（replace/add/remove/reorder）
- [ ] 编排层代码**原子应用**：预检全部动作（存在性/类型/位置），任一失败整体回滚、事务不提交
- [ ] 预算由代码重算覆盖（LLM 估值不可信）
- [ ] 修订受 DrivingGate 约束（自驾场景超限标记 critical 并反馈）

**Story 3（分享协作）**: 作为 owner，我想把行程分享给同行者，ta 无需注册即可看、评、投票、轻量编辑。
**验收要点**:
- [ ] 生成只读分享链接（幂等复用），持令牌免登录查看 + 预算汇总
- [ ] 评论（昵称可选，≤500 字，时间正序）；站点 👍/👎 投票（一访客一票、可翻转、幂等）
- [ ] owner 显式开放受邀编辑权（edit_token，与分享权限分离），受邀者可编辑
      站点 name/description/checked 与整日顺序，owner 可随时收回（链接立即失效）
- [ ] 只读分享不受收回编辑权影响（特权分离）

**Story 4（他人攻略导入）**: 作为旅行者，我粘贴小红书/公众号种草文本，想要洗成可勾选的站点候选。
**验收要点**:
- [ ] 纯规则解析，无 LLM、无外部 API、无成本
- [ ] 外部内容按敌意输入处理：指令型行标记剥离（flagged_lines），不进候选
- [ ] 返回候选清单（名称/类型/描述/估算费用/时长/来源行），前端勾选后走标准 stops 落库

**Story 5（Plan B 备选）**: 作为旅行者，我生成主行程后想快速看一个不同节奏/预算的对比方案。
**验收要点**:
- [ ] 确定性规则生成（节奏/预算档/取舍 三种变体之一），无 LLM 成本
- [ ] 只读派生：不落库、不改 trips 表、无副作用
- [ ] 行程无站点 → variant=None + note 说明（前端隐藏入口）

---

## 5. Solution Overview（方案概述）

### 5.1 总体架构

```
┌─ 前端 Vue3（可选）──────────────┐
│ TripListView / PlanWizard /      │
│ TripDetailView / ShareView /     │
│ AuthView + Leaflet 地图 + i18n   │
└──────────────┬───────────────────┘
               │ HTTP (JWT / token)
┌──────────────▼───────────────────┐
│ FastAPI 后端 (backend/)          │
│  api/v1: auth/trips/planner/     │
│    profile/plan_b/note_import/   │
│    health                        │
│  services: 业务逻辑（预算/修订/   │
│    协作/自驾/画像/规划/笔记导入/   │
│    PlanB）                       │
│  agent/: 多 Agent 编排 + 工具 +   │
│    providers                     │
│  oracle: models + schemas + alembic│
└──────┬────────────┬──────────────┘
       │            │
  PostgreSQL 17   LLM Providers
  (Docker)       deepseek/openai/ollama
                 + 高德/Tavily/wttr.in
```

### 5.2 规划主链路（4 Agent 协作 + 质检闭环）

1. 用户提交 `POST /planner/plan`（目的地/日期/人数/预算/偏好/questions）→ 立即返回 task_id；
2. 三个采集 Agent **并行执行**（`asyncio.gather`）：
   - `AttractionSearchAgent`（景点搜索专家）：偏好 → 关键词 → 高德 POI；
   - `WeatherQueryAgent`（天气查询专家）：城市 → 天气数据（**纯工具，不经过 LLM**）；
   - `HotelAgent`（酒店推荐专家）：住宿需求 → 关键词 → 高德 POI；
3. 编排层代码补位：餐饮 POI 搜索（美食是行程必备）+ 预算用 `compute_budget` 代码校准；
4. `PlannerAgent`（规划专家）：**不调用工具**，只整合团队产出，输出经 PlanSchema 强校验 + 失败自纠正；
5. `TravelCriticAgent`（质检）：按 schedule/budget/geography/logistics 四维打分，
   未过 80 分带结构化 issues 反馈 Planner 重生成；**最多 2 轮后强制定稿**；Critic 故障降级放行；
6. 结果落库（Trip + TripPlan 快照 + T-A-O trace），前端轮询展示实时轨迹。

### 5.3 修订链路（方案 B：AI 出 diff，代码执行）

1. 用户一句话修改请求 → `PlanReviseAgent` 解析为结构化 diff 指令；
2. 编排层代码**原子应用** diff：预检目标存在性/类型/位置 → 全部通过才执行；
3. 预算由代码重算；落库返回变更摘要；
4. 与手动编辑（PATCH 行内编辑 / PUT 整日排序）并存、互不覆盖。

### 5.4 关键设计决策

- **单一职责拆分**：每个 Agent 提示词 < 30 行，行为可预期，而非一个超长 prompt；
- **确定性兜底**：天气 = "城市→数据"纯工具（零 token）；预算 = 纯代码（城市基准价 × 档位倍率 ×
  评分修正）；自驾 = 确定性规则（120km/150min 单段、300km 单日）——**数学与事实交给代码**；
- **Evaluator-Optimizer 独立角色**：Critic 与 Planner 不同 system prompt + 独立调用，
  避免生成者自审自己的错；
- **修订"AI 出题、代码执行"**：LLM 只产 diff 指令，落库由代码原子应用，杜绝半生效状态；
- **特权分离**：share_token（只读）与 edit_token（受邀编辑）分离，收回编辑不影响只读分享；
- **外部内容当敌意源**：笔记导入按规则清洗，指令型行标记剥离。

---

## 6. 功能需求（Feature Requirements）

### F1 用户认证与账户（P0）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F1.1 | 注册 | 邮箱或手机号（至少一个）+ 密码 + 可选昵称 | 返回 access_token + user |
| F1.2 | 登录 | 邮箱或手机号 + 密码 | 返回 JWT（默认 7 天） |
| F1.3 | Google 登录 | Google ID Token 校验（aud 校验，公钥验证） | 未配置 `VITE_GOOGLE_CLIENT_ID` 时前端隐藏按钮 |
| F1.4 | 当前用户 | `GET /auth/me` | 需登录 |
| F1.5 | 用户隔离 | 行程/任务按 owner 隔离，JWT 鉴权 | 越权访问返回 404/403 |

### F2 行程管理（P0）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F2.1 | 行程 CRUD | 列表（分页 offset/limit ≤200）/创建/详情/更新/删除 | owner 隔离 |
| F2.2 | 日程（Day） | 增 / 批量按日期范围生成 / 删（级联站点） | generate_days 支持 `start`~`end` |
| F2.3 | 站点（Stop） | 增 / 删 / 编辑（PATCH 仅传入字段）/ 整日重排（PUT 幂等） | stop_type: attraction/food/hotel |

### F3 AI 多 Agent 规划（P0）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F3.1 | 异步任务 | `POST /planner/plan` 立即返回 task_id（202），`GET /tasks/{id}` 轮询 | 状态机 pending→running→completed/failed |
| F3.2 | 4 Agent 协作 | 3 采集 Agent 并行 + Planner 整合 | `asyncio.gather` |
| F3.3 | 真实数据源 | 高德 POI（AMAP_API_KEY）→ Tavily + Nominatim 降级；高德天气 → wttr.in | 无 key 也能跑 |
| F3.4 | LLM 输出强校验 | 所有 Agent 最终输出过 Pydantic Schema | 失败喂回 LLM 自纠正 ≤3 次 |
| F3.5 | 主动提问 | 规划请求可携带 questions（人群/节奏/避峰/备选）Q&A，答案并入上下文 | 前端 PlanWizard 4 个动态问题 |
| F3.6 | 用户画像注入 | `GET/PUT /profile`，画像摘要自动注入规划上下文 | 跨会话记忆 |

### F4 行程质检闭环（Evaluator-Optimizer）（P0）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F4.1 | Critic 四维评审 | schedule/budget/geography/logistics 打分 | 默认通过线 80 |
| F4.2 | 反馈重生成 | 结构化 issues → Planner 重生成 | 最多 `AGENT_MAX_REVIEW_ROUNDS`（默认 2）轮后强制定稿 |
| F4.3 | 降级放行 | Critic 自身失败 → 构造"通过"默认报告 | **绝不阻断主流程** |
| F4.4 | 质检 trace | 全程 T-A-O 轨迹随任务状态返回 | 错误可回溯到 Agent/步骤/校验 |

### F5 对话式行程修订（方案 B）（P0）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F5.1 | 自然语言修改 | `POST /trips/{id}/revise` + message | 返回变更摘要 + diff 明细 |
| F5.2 | diff 原子应用 | Replace/Add/Remove/Reorder 预检后执行 | 任一失败整体回滚，事务不提交 |
| F5.3 | 预算重算 | 修订后代码重算预算 | 不信任 LLM 估值 |
| F5.4 | 受 DrivingGate 约束 | 自驾场景超限标记 critical 反馈 | 修订同样过门 |

### F6 手动细粒度编辑（P1）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F6.1 | 行内编辑站点 | PATCH 仅更新传入字段 | 与 AI 修订并存 |
| F6.2 | 整日排序 | PUT 全量站点 id 顺序（幂等） | 用于上移/下移/拖拽 |

### F7 预算计算（P0）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F7.1 | 预算明细 | `GET /trips/{id}/budget` | 按站点类型（景点/餐饮/住宿）汇总 |
| F7.2 | 确定性估算 | 酒店城市基准价 × 档位倍率 × 评分修正；景点/餐饮类目参考价 | 无外部依赖、可测试 |

### F8 自驾模式校验（DrivingGate）（P1）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F8.1 | 单段校验 | 同一天相邻站点距离 ≤120km、时长 ≤150min | 默认均速 50km/h 球面距离 |
| F8.2 | 单日累计 | 单日累计里程 ≤300km | 超限标记 critical |
| F8.3 | 反馈重生成 | 校验失败带问题反馈 Planner | 规划与修订链路均受约束 |

### F9 分享与多人协作（P1）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F9.1 | 只读分享 | `POST /trips/{id}/share` 生成 share_token（幂等复用） | 免登录只读 + 预算汇总 |
| F9.2 | 评论 | 分享页评论列表/发表（昵称可选，≤500 字） | 免登录 |
| F9.3 | 投票 | 站点 👍/👎，一访客一票可翻转（voter_key = token+IP+UA 哈希） | 幂等，唯一约束 stop+voter |
| F9.4 | 受邀编辑权 | `POST/DELETE /trips/{id}/share/edit` 开放/收回 edit_token | 持令牌可编辑受限字段（name/description/checked）+ 整日排序；收回立即失效 |
| F9.5 | 特权分离 | 只读分享不受收回编辑影响 | share/edit_token 双列独立 |

### F10 笔记导入（P1）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F10.1 | 攻略解析 | `POST /trips/note/import` 粘贴文本 → 站点候选 | 纯规则，无 LLM/API 成本 |
| F10.2 | 敌意输入处理 | 指令型行标记剥离（flagged_lines），不进候选 | 返回 dropped_lines 统计 |
| F10.3 | 勾选落库 | 候选前端勾选后走标准 `POST /trips/days/{day_id}/stops` | 复用现有链路 |

### F11 Plan B 备选方案（P2）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F11.1 | 备选骨架 | `GET /trips/{trip_id}/plan-b` 节奏/预算档/取舍 三变体之一 | 确定性规则，无 LLM 成本 |
| F11.2 | 只读派生 | 不落库、不改表、无副作用 | 行程无站点 → variant=None + note |

### F12 前端（P1）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F12.1 | 行程列表 | 分页卡片 + 手动创建入口 | 每页 9 |
| F12.2 | 规划向导 | 表单 + 主动提问 4 问 + Provider 选择 + 实时 T-A-O 轨迹 + 质检卡片 | 酒店推荐组件 |
| F12.3 | 行程详情 | 地图（Leaflet）+ 预算 + 酒店推荐 + 导出图片/PDF + AI 调整对话 + 手动编辑/排序 | 导出用 `html2canvas`/pdf 工具 |
| F12.4 | 分享页 | 只读 + 评论 + 投票 + `?edit=1` 受邀编辑模式 | 免登录 |
| F12.5 | 认证 | 登录/注册 + Google 按钮（可隐藏） | Token 持久化 |
| F12.6 | i18n | vue-i18n 9，zh-CN/en-US，顶栏切换 + Element Plus locale 联动 | 三大业务视图已迁移 |

### F13 系统级容错与可观测（P0，横切）
| ID | 需求 | 说明 | 验收要点 |
|----|------|------|----------|
| F13.1 | 指数退避重试 | LLM 瞬时故障（网络/超时/限流/5xx） | `LLM_MAX_RETRIES`=3，0.5s→8s |
| F13.2 | 熔断器 | 滑动窗口失败率，OPEN → 冷却 → HALF-OPEN | 阈值 3 / 冷却 30s |
| F13.3 | Provider 兜底 | deepseek → openai → ollama（可开关） | `ENABLE_PROVIDER_FALLBACK` |
| F13.4 | 任务超时/恢复 | `TASK_EXECUTION_TIMEOUT`=180s 超时标记 failed；启动扫描遗留 running | 不卡死 worker |
| F13.5 | 健康检查 | `GET /health` DB 故障返回 `degraded` 而非 500（3s 超时独立连接） | 负载均衡据此摘除 |
| F13.6 | 成本估算 | 配置单价后 trace 写入 cost_usd | 可选 |
| F13.7 | 结构化日志 | 全链路可回溯 | 每步降级/校验有日志 |

---

## 7. Technical Considerations（技术考量）

### 7.1 技术栈
- **后端**: FastAPI + SQLAlchemy 2 (async) + asyncpg + Pydantic v2 + Alembic（PostgreSQL 17）
- **Agent**: LangGraph/LangChain（编排收敛在 `app/agent/`，LangGraph 原型保留 `graph.py`）
- **数据源**: 高德 POI/天气（AMAP_API_KEY）+ Tavily + wttr.in + Nominatim（降级链）
- **LLM**: DeepSeek / OpenAI 兼容 / Ollama（`DEFAULT_LLM_PROVIDER=auto`）
- **前端**: Vue3 + Vite + Element Plus + Leaflet + vue-i18n
- **测试**: pytest + httpx + **FakeLLM 测试替身**（95 个测试，零 token、零网络）

### 7.2 依赖与风险
| 依赖 | 用途 | 风险 |
|------|------|------|
| PostgreSQL 17（Docker） | 持久化 | 无 DB 则降级；health degraded 语义 |
| LLM Provider keys | 规划/修订/质检 | 熔断 + 兜底链缓解 |
| 高德 Web API key（可选） | POI/天气 | 未配置自动降级 Tavily/wttr.in |
| 免费 POI 无价格 | 预算精度 | 已用代码确定性估算缓解 |

### 7.3 待解决问题（Open Questions）
- [ ] 规划任务成功率的线上埋点与基线采集 — Owner: PM — 待接入
- [ ] revise/plan-b 前端入口完整度（plan-b 是否有 UI 入口） — Owner: FE — 排查中

---

## 8. Launch Plan（发布计划/当前状态）

| Phase | 状态 | 说明 |
|-------|------|------|
| 核心规划链路（F1-F5/F7/F13） | ✅ Shipped | Agent 协作 + 质检 + 修订 + 容错 |
| 协作分享（F9） | ✅ Shipped | 评论/投票/受邀编辑 |
| 自驾校验（F8） | ✅ Shipped | DrivingGate |
| 手动编辑（F6） | ✅ Shipped | PATCH/PUT |
| 画像与提问（F3.5/3.6） | ✅ Shipped | 跨会话记忆 |
| 笔记导入（F10） | ✅ Shipped | 夜间流水线 2026-09-25 |
| Plan B（F11） | 🟡 Shipped（API）+ 待前端入口 | 2026-09-25 |
| i18n（F12.6） | 🟡 三大业务视图进行中 | task-i18n-views |
| 预订/支付闭环 | 🔴 不做（Non-Goal） | 方案 C 未做 |

---

## 9. 数据模型（简）

- **User**（users）: id / email / phone / password_hash / display_name / provider / created_at
- **UserProfile**（user_profiles）: traveler_type / pace / budget_tier / favorite_cities / preferences_json
- **Trip**（trips）: title / destination / start_date / end_date / travelers / budget / status / **share_token** / **edit_token** / owner
- **TripDay**（trip_days）: day_number / date / note（级联删）
- **Stop**（stops）: order_index / name / stop_type（attraction/food/hotel）/ lat / lng / description / estimated_cost / estimated_duration_minutes / **checked** / details(JSON)（级联删）
- **TripPlan**（trip_plans）: plan_data(JSON 快照) / trace(JSON) / provider / model / status / error_message
- **PlanTask**（plan_tasks）: request_data(JSON) / status / trace / plan / trip_id / error_message / started_at / finished_at
- **TripComment**（trip_comments）: author_name / content(≤500)
- **StopVote**（stop_votes）: stop_id + voter_key（唯一约束）/ value(1/-1)

---

## 10. API 清单（已实现）

### 认证 / 健康 / 画像
| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/auth/register` | 注册（邮箱或手机号） |
| POST | `/api/v1/auth/login` | 登录，返回 JWT |
| POST | `/api/v1/auth/google` | Google ID Token 登录 |
| GET | `/api/v1/auth/me` | 当前用户（登录） |
| GET | `/api/v1/health` | 健康检查（degraded 语义） |
| GET/PUT | `/api/v1/profile` | 用户画像读 / 全量 upsert |

### 行程 / 日程 / 站点
| Method | Path | 说明 |
|--------|------|------|
| GET/POST | `/api/v1/trips` | 列表（分页）/ 创建 |
| GET/PATCH/DELETE | `/api/v1/trips/{id}` | 详情 / 更新 / 删除 |
| POST | `/api/v1/trips/{id}/days` | 添加日程 |
| POST | `/api/v1/trips/{id}/days/generate` | 按日期范围批量生成 |
| POST | `/api/v1/trips/days/{day_id}/stops` | 添加站点 |
| PATCH | `/api/v1/trips/days/{day_id}/stops/{stop_id}` | 编辑站点（仅传入字段） |
| PUT | `/api/v1/trips/days/{day_id}/stops/order` | 整日重排（幂等） |
| DELETE | `/api/v1/trips/days/{day_id}` 及 `/stops/{stop_id}` | 删除 |
| GET | `/api/v1/trips/{id}/budget` | 预算明细 |
| GET | `/api/v1/trips/{id}/plan` | Agent 方案快照（含酒店推荐） |

### 修订 / 分享协作
| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/trips/{id}/revise` | 对话式修订（AI diff + 代码原子执行） |
| POST | `/api/v1/trips/{id}/share` | 生成只读分享（幂等） |
| GET | `/api/v1/trips/share/{token}` | 免登录只读 + 预算汇总 |
| GET/POST | `/api/v1/trips/share/{token}/comments` | 评论列表 / 发表（免登录） |
| GET/POST | `/api/v1/trips/share/{token}/votes[/{stop_id}]` | 投票汇总 / 投票翻转（免登录） |
| POST/DELETE | `/api/v1/trips/{id}/share/edit` | 开放 / 收回受邀编辑权 |
| GET | `/api/v1/trips/edit/{token}` | 受邀查看（含预算） |
| PATCH | `/api/v1/trips/edit/{token}/stops/{stop_id}` | 受邀编辑受限字段 |
| PUT | `/api/v1/trips/edit/{token}/days/{day_id}/stops/order` | 受邀整日重排 |

### AI 规划 / 内容工具
| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/planner/plan` | 提交 AI 规划任务（异步，202） |
| GET | `/api/v1/planner/tasks/{task_id}` | 轮询状态（含 trace） |
| POST | `/api/v1/trips/note/import` | 笔记/攻略解析为站点候选 |
| GET | `/api/v1/trips/{trip_id}/plan-b` | Plan B 备选骨架 |

> 除 `/auth/*` 与 `/health` 外全部需 `Authorization: Bearer <jwt>`。

---

## 11. 测试策略（现状）

95 个 pytest 测试，**全部使用 FakeLLM 测试替身，不消耗真实 token、不依赖网络**：
- health / 行程 CRUD / 日程站点 / 预算（含酒店城市基准价估算）
- 异步规划任务全链路（FakeLLM）
- LLM 输出 schema 校验与自纠正 / owner 用户隔离
- 对话式修订（diff 原子应用）/ 分享、评论、投票、受邀编辑权
- 自驾校验（DrivingGate）/ 主动提问与画像注入 / Google 登录
- 笔记导入（规则解析 + 敌意输入）/ Plan B

---

## 12. 已知局限（诚实清单）

| 局限 | 影响 | 状态 |
|------|------|------|
| 高德免费 POI 不返回价格，estimated_cost 多为 0 | 预算精度有限 | ✅ 代码确定性估算缓解 |
| 无预订/支付闭环 | 用户不能直接下单 | 不做（Non-Goal） |
| LLM 质量受模型上限 | 复杂定制可能不完美 | ✅ Critic 四维质检 + 重生成缓解 |
| 管道式编排非协商式 | Agent 间不互相讨论 | ✅ plan-then-review 部分解决 |
| 行程是静态快照 | 旅行中不可实时交互 | ✅ 对话修订 + 手动编辑 + 受邀编辑 |
| 匿名令牌协作 | 无法识别真实用户；token 泄露即授信 | 可选改进：令牌绑定/过期/审计 |
| 自驾基于球面距离估算 | 与实际道路有偏差 | 可选：高德路径规划 API |
| 移动端未专门优化 | 小屏适配一般 | 可选：响应式 |
| en-US 部分硬编码中文 | 多语言不完整 | 🟡 进行中 |
| 无 7×24 人工兜底 | 极端场景无真人 | ✅ 工程化降级链 + 可回溯 trace |

---

## 13. 附录

- 技术架构与编排图：`README.md`
- 技术文章（深厚沉淀）：`docs/articles/01~08`
- 夜间迭代任务源：`docs/night-build-todo.md` / 运行契约 `docs/night-build-manual.md`
- 竞品分析：`docs/nightly/competitive-analysis/`
- 质量与兜底设计：README「质量与兜底」小节