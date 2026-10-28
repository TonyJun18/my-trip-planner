# 迭代需求规格说明书（SRS）：预订打通 · 旅程追踪 · 朋友圈晒图

**Status**: Draft（待评审）  **Author**: Alex (PM)  **Last Updated**: 2026-10-28  **Version**: 1.0
**Stakeholders**: 彭军（唯一开发者/owner）、夜间流水线 night-worker、Alex (PM)
**关联方案**:
- `docs/plans/2026-10-28-booking-schemes.md`（预订：A outlink / B 会话式 / C 开放平台）
- `docs/plans/2026-10-28-trip-journey-xhs-schemes.md`（追踪：A 时间轴 / B 护照徽章；晒图：C 高光卡）

> 本文档把三份候选方案收敛为**可执行的迭代需求**。每条 Story 有明确验收标准（可验证、不依赖真实外部环境），严格遵循仓库"规划层"定位与既有工程纪律。

---

## 1. 背景问题（Problem Statement）

**现状（代码实查）**：产品已具备规划（多 Agent 编排）、修订（diff 原子应用 + 质检闭环）、协作（投票/consensus）、行中（live 打卡/顺延）、记账（expense 分摊）、晒图（xhs 文案工厂）、输入自由（四通道导入）、可观测（trace/事件流）——**规划层深度是差异化护城河**。

**缺口（本次迭代要解决的）**：
1. **预订未打通**：行程里的交通/住宿只是"建议"，不是"可预订实体"；无外链引导、无订单回填、无凭证落库。
2. **旅程行为零汇总**：打卡/费用/事件流分散且无投影聚合，用户（和同伴）无法"回看全程"、无法形成"旅程故事"素材。
3. **晒图只有"出发前攻略"**：缺"行中/行后真实数据"驱动的朋友圈素材。

**不解决的代价**：规划完即结束，缺乏"预订引导 + 行中沉淀 + 出圈分享"的闭环；在 OTA 把规划当漏斗入口的竞争格局下，独立规划层价值被稀释（docs/articles/06、10、14 已有论证）。

---

## 2. Goals & Success Metrics（目标与成功指标）

| Goal | Metric | Current Baseline | Target | Window |
|------|--------|-----------------|--------|--------|
| 预订引导可用 | 行程内"可预订"外链产出率（有 transport/hotel 的行程含 booking 建议） | 0（无预订功能） | ≥ 90% | 上线后 30 天 |
| 订单回填闭环 | 用户回填订单（email/screenshot/manual）成功率 | 0（无回填入口） | ≥ 80% 尝试成功 | 上线后 30 天 |
| 旅程可回看 | 详情页"旅程时间轴"对已产生事件的行程 100% 可渲染 | 0（无投影） | 100% | 每任务验收 |
| 追踪激励 | 打卡/记账用户中"旅程护照"点亮 ≥ 1 徽章占比 | 0（无徽章） | ≥ 30%（人工抽样） | 30 天 |
| 晒图出圈 | 故事卡生成成功率（LLM 失败走模板） | 0（只有攻略文案） | ≥ 95% | 每任务验收 |
| 后端测试 | 新增模块专项测试全绿（不依赖外部/LLM mock） | 314 tests | 新增 ≥ 40 tests，全绿 | 每任务 CI |
| 前端构建 | `npm run build` 通过 | 通过 | 保持通过 | 每任务 CI |

> 注：无真实用户/无埋点，转化率类指标只能标记"待埋点"，不编造。

---

## 3. Scope（范围）

### 3.1 In Scope（本轮迭代做）
- **预订（选型 A outlink 为 P0）**：BookingAgent + `plan.bookings` + `TripBooking` 表 + 回填（email/screenshot/manual）+ 预订卡 UI + booking.* 事件
- **追踪（A 时间轴为 P0，B 护照为 P1）**：journey 投影（打卡进度/费用汇总/按天状态）+ 旅程时间轴 UI；护照徽章（确定性规则）
- **晒图（C 高光卡为 P1）**：trip_story 服务（投影→故事，LLM→模板降级）+ 渠道模板（小红书/朋友圈/通用长图）
- **跨域**：事件类型扩展（booking.*、story.*）、i18n、测试、可观测
- **工程基线**：全部复用既有 PipelineStep / servicing / 降级链 / trace / 测试纪律

### 3.2 Out of Scope（明确不做）
- 不碰支付牌照 / 资金池 / 代收代付（预订方案 Non-Goal）
- 不做 GDS / Sabre / Amadeus 直连、不做开放平台 C 的资质申请（当前阶段）
- 不做实时 GPS 轨迹采集、不做原生推送/锁屏（追踪方案 Non-Goal）
- 不做陌生人社交 / 社区 Feed；晒图只做"导出到公域"，不接公域发布 API
- 不做多币种结算；预算口径保持 CNY
- 不做营销归因 SDK / 第三方转化追踪

---

## 4. User Personas & Stories（用户画像与故事）

**Primary Persona（小刘）**：28 岁城市白领，预算敏感（3k 级），周末/小长假出游；会用 AI 工具但吃过"AI 编造行程"的亏，重视信息真实与行程可调整；旅行中习惯随手记一笔、回来发朋友圈。

**Secondary Persona（同行旅伴）**：拿到分享链接的人，免登录评论/投票/打卡；想回看"我们这次一起做了什么"。

### Story 1（可预订：外链引导）
作为旅行者，我想要在行程里看到交通/酒店"一键预订"入口（直达 OTA 搜索页），以便不用手动去各平台找。

**Acceptance Criteria**:
- [ ] 包含"大交通（高铁/飞机）或酒店"的行程，规划完成后 `plan.bookings` 产出可预订建议（provider/kind/title/provider_url/price_estimate）
- [ ] 预订卡前端展示 provider 标签 + 预估价格 + "去预订"按钮（新标签页跳 provider_url）
- [ ] BookingAgent 失败/LLM 超时 → 静默降级：不产出 bookings，plan 照常落库，前端无预订卡（不阻断主流程）
- [ ] `provider_url` 为纯规则组装（`_deeplink` 纯函数），未知 provider 返回 None 不伪造
- [ ] 文案只承诺"跳转预订"，无"已订/占座/确认"字样（防幻觉）
- [ ] 后端测试 ≥ 8 例（URL 模板/降级/未知 provider）

### Story 2（可预订：订单回填）
作为旅行者，我想要从 OTA 订完后把凭证带回行程（粘贴确认邮件/截图/手动），以便订单与行程关联、行中可查。

**Acceptance Criteria**:
- [ ] 预订卡提供"我订好了"→ 复用 email_import / screenshot_import / manual 三种回填路径
- [ ] `TripBooking` 落库：provider/kind/title/order_no/credential/status/amount，无重复（唯一键 provider+order_no 幂等 upsert）
- [ ] 状态机：suggested → pending → confirmed（带凭证/回调）⇄ cancelled；confirmed 需有凭证号（强校验）
- [ ] confirmed 订单可一键"记一笔账"（category=transport/hotel，复用 expense_service）
- [ ] 记录 `booking.confirmed` / `booking.cancelled` 事件进 TripEvent + WS 广播
- [ ] 后端测试 ≥ 10 例（回填解析/幂等/状态机/事件）

### Story 3（追踪：旅程时间轴）
作为旅行者/同伴，我想要在详情页看到"这次旅行到今天做了什么"（按天打卡、费用、进度），以便全程可回看。

**Acceptance Criteria**:
- [ ] `GET /trips/{id}/journey` 返回投影：journey_progress（打卡/总站点）、day_status[]、expense_total/by_category/per_person（复用 compute_balance）、highlights[]（来自 check/delay/vote 事件）
- [ ] 纯读时聚合（不落新表）；事件流为空 → 返回全零 + "旅途尚未开始"标识（前端空态，不报错）
- [ ] 时间轴按天分组（已完成打卡/跳过/费用/评论/预订事件，倒序）
- [ ] 前端 JourneyTimeline.vue + TripDetailView 接入；i18n zh/en 键齐全
- [ ] 后端测试 ≥ 12 例（投影聚合/空事件/部分事件/超长分页/费用口径）

### Story 4（追踪：旅程护照徽章，P1）
作为旅行者，我想要看到"我集齐了哪些旅程徽章"，以便获得完成感和分享素材。

**Acceptance Criteria**:
- [ ] `TripPassport` 表（trip_id 唯一）+ 徽章规则库（确定性，不经过 LLM）：first_checkin / full_day / money_saver / train_goer / hotel_stayer / early_bird / night_owl
- [ ] `record_event` 后 hook `maybe_award`（幂等：badge 已存在跳过；事件乱序按 created_at 排序）
- [ ] 历史回填：已有行程一次性投影徽章
- [ ] ShareView 增加"旅程护照"区块（徽章墙 + 进度 + 免登录只读）
- [ ] 后端测试 ≥ 10 例（规则全路径/幂等/历史回填/只读）

### Story 5（晒图：旅程高光卡，P1）
作为旅行者，我想要把"这次真实旅行"一键生成朋友圈/小红书素材（足迹榜 + 账单 + 徽章墙），以便晒图朋友圈。

**Acceptance Criteria**:
- [ ] `POST /trips/{id}/story` 基于 journey 投影 + passport + expenses 生成故事（LLM 主路径 → 模板兜底，source 标记 llm/template，复用 xhs 降级哲学）
- [ ] 三类产物：小红书（标题/正文/话题，复用 XhsNoteDialog）、朋友圈（短文案 + 封面卡预览）、通用长图（HTML 卡片，可浏览器截图/保存）
- [ ] 数据不造假：只输出已记录事件数据（打卡数/费用/徽章/站点名），无记录的不推断；凭证号绝不进文案
- [ ] 投影为空 → 引导"先记一笔/打一次卡"，不硬生成（空态提示）
- [ ] 前端 StoryCardGenerator.vue 渠道选择 + 编辑 + 复制；i18n zh/en
- [ ] 后端测试 ≥ 10 例（模板生成/LLM 降级/空投影/PII 过滤）

---

## 5. 功能需求（含跨 Story 的系统性需求）

### 5.1 预订模块
- `BookingAgent`（PipelineStep，Collect 段后）输入 Plan → 输出 `plan.bookings[]`（字段：kind/provider/title/provider_url/price_estimate/reference/status）
- `BookingProvider` 枚举：ctrip / qunar / 12306 / feizhu / tongcheng / manual
- `TripBooking` 表 + 状态机 + 幂等 upsert + expense 联动
- event_type 新增：`booking.suggested` / `booking.pending` / `booking.confirmed` / `booking.cancelled`
- 降级链：LLM 整理 → 纯规则模板 → 不产出 bookings（不阻断主流程）

### 5.2 追踪模块
- `journey_service.projection(trip)`：读时聚合 TripEvent + TripExpense + TripBooking（无新表）
- `TripPassport` 表 + 徽章规则库（hook 幂等触发 + 历史回填）
- 事件扩展：`booking.*` / `story.generated` 进入 TripEvent 投影

### 5.3 晒图模块
- `trip_story_service`（LLM → 模板兜底，source 标注）+ 三类渠道模板
- PII 过滤（name/金额/日期白名单；凭证号/确认码绝不进文案）
- 空投影引导（不硬生成）

### 5.4 工程与可观测
- 所有新增服务/路由注册进既有 `PipelineStep` / trips 子域路由模式
- `trace_id` 贯穿预订/追踪/晒图链路；成本/延迟按模块追踪
- i18n 键两侧（zh-CN/en-US）齐全
- 测试纪律：mock LLM、不依赖外部环境、纯函数优先

---

## 6. 迭代计划（分 3 期）

| 期 | 范围 | 预估 | 依赖 | 验收出口 |
|---|---|---|---|---|
| **P0（本期）** | 预订 A（outlink + 回填）+ 追踪 A（时间轴） | 2-3 sprint | 复用现有 PipelineStep / live / expense / email-import | 全套后端测试 + 前端 build + 手工验收清单 |
| **P1** | 追踪 B（护照徽章）+ 晒图 C（高光卡模板先行） | 2-3 sprint | P0 的 journey 投影 + 事件 hook | 全套测试 + build + 手工验收 |
| **P2（观察）** | 预订 B（会话式）/ C（开放平台）评估 | 评估 | 真实用户规模信号 | 评估记录 +（若可行）MVP |

> 每期遵循仓库任务登记制：进 `docs/night-build-todo.md` + checkpoint；实现前跑 `verify-work-before-implement` 侦察（查已有实现/WIP）。

---

## 7. 验收办法与发布标准（系统验收）

**自动化验收（每任务必过）**
1. `cd backend && .venv/bin/python -m pytest -q` 全套绿（新增 ≥ 40 例专项）
2. `cd frontend && npm run build` 通过
3. i18n 键 zh/en 两侧齐全（引用即定义）
4. 不依赖外部环境（LLM mock、无真实 OTA/API 调用）

**手工验收清单（发布前人工过）**
- [ ] 一份含高铁 + 酒店的测试行程：规划完成 → 预订卡出现 → 跳转外链可达 →"我订好了"回填凭证 → confirmed 状态 → 一键记账
- [ ] 行中打卡/记一笔 → 详情页时间轴实时更新；同伴分享页可见
- [ ] 生成故事卡：小红书/朋友圈/长图三渠道产物可编辑可复制；无 PII 泄露
- [ ] 断网/LLM 故障：预订卡不阻断规划；故事卡走模板；抽测降级路径
- [ ] 移动端 375px：预订卡/时间轴/护照/故事卡无横向滚动、触控可用

**发布门禁（Go/No-Go）**
- 后端 100% 测试绿 + 前端 build 绿
- 至少一次端到端手工验收通过（含降级路径）
- 文档：3 份方案 + 本 SRS 已入库（docs/plans + docs/prd）

---

## 8. 非功能需求（NFR）

| 维度 | 要求 |
|---|---|
| 性能 | journey 投影读时聚合 < 200ms（31 天行程）；预订 URL 组装 < 10ms（纯函数） |
| 安全 | 回填输入按敌意输入处理（复用 note-import 剥离）；外链 URL 白名单域名校验（防开放重定向）；凭证号不落日志/文案 |
| 合规 | 不代收资金；订价/退改以渠道为准展示；晒图可关金额 |
| 可靠性 | 预订/故事全链路降级：LLM 失败→模板→不产出；主流程永不阻塞 |
| 可观测 | 每次预订/追踪/晒图调用带 trace_id + 结构化日志（LOG_FORMAT=json） |
| 可维护 | 纯函数优先（_deeplink/_projection/徽章规则）；新服务注册进既有路由/PipelineStep 模式 |

---

## 9. 风险与依赖

| 风险 | 等级 | 缓解 |
|---|---|---|
| OTA 外链被改规则（Story 1 可用性） | 中 | URL 模板版本化 + 前端 404 降级 + 运营可配置 |
| 用户不打卡 → 追踪/晒图数据空（Story 3/5） | 中 | UI 引导打卡/记账；徽章激励（Story 4）；空态不硬造 |
| 预订回填解析率受渠道邮件格式影响（Story 2） | 中 | email_import 已有解析 + manual 兜底 |
| 护照徽章沦为"打卡机器" | 低 | 规则库克制（7 个初始徽章）+ 测试覆盖 |
| 长图导出跨端不一致（Story 5） | 中 | 先用浏览器截图保底，服务端渲染后置 |

---

## 10. 待决策项（评审表，需用户拍板）

| # | 决策 | 选项 | 建议 |
|---|---|---|---|
| 1 | 预订短期路线 | A outlink / B 会话式 / C 开放平台 / 组合 | **A 先行**（P0），B/C 观察 |
| 2 | 追踪是否上徽章（P1 护照） | 只做时间轴 / 加护照 | 先 A 后 B，徽章 P1 |
| 3 | 晒图长图形态 | 前端截图保底 / 服务端渲染 | 前端截图先行 |
| 4 | 是否开放"C 资质申请"排期 | 排队 / 立项 | 有真实用户规模再立项 |

---

## 11. 附录：与既有资产映射

| 本次需求 | 复用/扩展的现有资产 |
|---|---|
| BookingAgent | pipeline.py PipelineStep 机制 · servicing 降级链 · xhs/checkin LLM+模板模式 |
| TripBooking | TripExpense 记账哲学 · TripEvent 事件流 · share/edit 令牌语义 |
| journey 投影 | live_service.trip_phase/today_day · event_service · expense.compute_balance |
| 护照徽章 | TripEvent hook · live 打卡 · booking confirmed |
| 故事卡 | xhs_service（LLM→模板）· XhsNoteDialog 复制/编辑模式 · 分享头图资产 |

---

*本 SRS 是迭代需求基线；实际排期/任务拆分以 `docs/night-build-todo.md` 登记为准。*