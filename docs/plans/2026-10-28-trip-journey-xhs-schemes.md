# 旅程全程追踪 + 朋友圈晒图方案

**作者**: Alex (PM)  **日期**: 2026-10-28  **版本**: v1.0（候选方案评审稿，未批准）
**状态**: 候选方案——2 条追踪路线 + 1 条晒图路线并行评审，需用户拍板
**关联**: `docs/plans/2026-10-28-booking-schemes.md`（预订打通）· `docs/prd/2026-10-28-iteration-spec.md`（需求规格说明书）

---

## 1. 背景与已具备的资产

**"追踪用户旅程行为"的现状盘点**（代码实查，非猜测）：

| 能力 | 现状 | 落点 |
|---|---|---|
| 行程状态机 | ✅ 已有 `trip_phase`（upcoming/live/finished） | `live_service.py` |
| 行中打卡 | ✅ check/skip/delay_today（免登录 token 双路径） | `live_service.py` |
| 行中事件流 | ✅ `TripEvent`（revise/check/skip/delay/comment/vote/edit/share）+ WS 广播 | `event_service.py` + `TripEvent` 表 |
| 费用记录 | ✅ append-only 记账 + 分摊 | `expense_service.py` |
| 行为画像 | ✅ `user_profiles.behavior_memory_json` + preference_service | `models/profile.py` |
| 朋友圈晒图（内容工厂） | ✅ `xhs_service.generate_xhs_note`（LLM 主路径 → 模板兜底）+ 前端 XhsNoteDialog（编辑/复制） | `xhs_service.py` + `XhsNoteDialog.vue` |
| 预订凭证 | ❌ 无（与预订方案同源，见 `2026-10-28-booking-schemes.md`） | — |

**一句话现状**：行中打卡/顺延/费用/事件流已具备，但**打卡数据零汇总、零可视、零沉淀**——低频单条翻译不成"这次旅行完整的故事"；晒图目前只有"出发前静态攻略文案"，没有"真实行中数据（实际走了哪、花了多少、打了哪些卡）"作为素材。

---

## 2. 目标与 Non-Goals

### Goals
1. 用**已有的行中事件流**沉淀出一个可回看的"旅程时间轴"，让用户（和同伴）能看到全程发生了什么；
2. 把"打卡/费用/预订"数据聚合出**可分享的"旅程账单 + 足迹页"**，成为朋友圈晒图的素材源；
3. 晒图从"攻略模板"升级为"真实行程数据 + AI 文案"，并支持多种渠道（小红书/朋友圈/通用长图）。

### Non-Goals
- **不做实时 GPS 轨迹采集**（无定位权限/后台运行，隐私与耗电成本高）
- **不做原生推送/锁屏**（PWA 通知已够，Live Activities 等原生能力不做）
- **不做陌生人社交/Feed**（行程是私有资产，晒图是"导出到公域"，不是"社区"）
- **不做营销归因 SDK**（不采集第三方平台转化）——晒图只做内容生成，不做商业追踪

---

## 3. 追踪路线 A — 轻量时间轴（零新表，复用事件流）

> 核心判断：`TripEvent` 已经是 append-only 的事实流，只差一个"投影"视图。

### 3.1 做法
- **数据投影**：新增 `journey_service.projection(trip)` —— 读 `TripEvent`（+ `TripExpense` + `TripBooking`）聚合为"旅程状态机快照"：
  - `journey_progress`：已打卡站点数 / 总站点数 × 100%
  - `day_status[]`：每天 completed/partial/todo（按 check 事件 + 站点总数）
  - `expense_total` / `by_category` / `per_person`（复用 `compute_balance`）
  - `booking_status[]`：suggested/pending/confirmed/cancelled（接预订方案的 TripBooking）
  - `highlights[]`：从 check/delay/vote 事件里挑"有故事"的（如"Day2 西湖 已打卡"）
- **不落新表**：投影是读时聚合（每次 GET 现算，或用前端缓存），事件流永远是唯一事实源
- **前端**：TripDetailView 增加"旅程"Tab 或时间轴区——按天分组的事件流 + 进度环；无需注册新事件类型

### 3.2 涉及文件
- `backend/app/services/journey_service.py`（新增：投影 + 聚合纯函数，可单测）
- `backend/app/api/v1/trips_journey.py`（新增：GET /trips/{id}/journey）
- `backend/app/schemas/journey.py`（新增：JourneyOut / DayJourney / Highlight）
- `frontend/src/components/JourneyTimeline.vue`（新增）+ TripDetailView 接入
- `frontend/src/locales/{zh-CN,en-US}.js`：i18n 键
- `backend/tests/test_journey_service.py` / `test_journey_api.py`

### 3.3 故障模式
| 故障 | 检测 | 恢复 |
|---|---|---|
| 事件流为空（用户没打卡） | projection 全 0 | 前端显示"旅途尚未开始"空态，不报错 |
| 事件流缺失（部分打卡没记上） | 投影 vs 行程站点数差异 | 只按已有事件算，标注"部分数据"诚实口径 |
| 并发写事件 | 事件表 append-only | 读时聚合天然无竞态（不写共享状态） |
| 超长行程（31 天） | 投影数据量大 | 前端按天懒加载，接口分页 |

### 3.4 优点 / 风险
- ✅ 零新表、零新事件，纯投影——成本最低、可测试、可回滚
- ✅ 直接复用已有的 check/skip/delay/expense 数据，用户已产生的行为马上有回报
- ⚠ 依赖事件流完整度：若用户不打卡，追踪内容是空的（需在文案/UI 上引导"完成一天，记一笔"）

---

## 4. 追踪路线 B — 旅程护照（TripPassport，状态机 + 徽章体系）

> 在 A 的基础上加"激励层"：把旅程变成可收集的护照/徽章，晒图素材自带"完成感"。

### 4.1 做法
- **状态机升级**：`TripPassport` 表（trip_id 唯一）：`phase`（upcoming/live/finished）、`badges[]`、`mileage_since_state` 累计、`last_progress_at`、`share_token`
- **徽章规则库**（纯确定性，不经过 LLM）：
  - `first_checkin`（第一次打卡）
  - `full_day`（某天全部站点完成）
  - `money_saver`（实际花费 < 预算 90%）
  - `train_goer` / `hotel_stayer`（预订方案 confirmed 后触发）
  - `early_bird`（行程开始前进过 3+ 次修订）
  - `night_owl`（有 22:00 后的 check 事件）
- **触发**：事件写入 TripEvent 后 hook 一次"徽章判定"（幂等，badges 只增不减；历史回填一次性投影）
- **分享页**：ShareView 增加"旅程护照"区块——徽章墙 + 进度 + 费用 + 打卡时间线，免登录可看
- **诚实口径**：徽章只依据已产生的事件，不推断"没打卡但我想他去了"

### 4.2 涉及文件
- `backend/app/models/trip.py`：`TripPassport` 表
- `backend/app/services/passport_service.py`（新增：徽章规则 + 状态机 + 幂等触发）
- `backend/app/services/event_service.py`：`record_event` 后 hook `passport_service.maybe_award`
- `backend/app/api/v1/trips_passport.py`：GET /trips/{id}/passport
- `backend/app/schemas/passport.py`：PassportOut / BadgeOut
- `backend/app/services/journey_service.py`：A 路线的投影供 passport 复用
- `backend/tests/test_passport_service.py`（徽章规则全路径 + 幂等 + 历史回填 + 分享只读）
- `frontend/src/components/PassportPanel.vue` + ShareView 接入

### 4.3 故障模式
| 故障 | 检测 | 恢复 |
|---|---|---|
| 徽章判定重复触发 | 幂等（badge 已存在则跳过） | 记录 event 但不再 award |
| 事件乱序/迟到补打卡 | 按事件 created_at 排序后判定 | 顺延判定窗口（只认已提交事件） |
| share_token 泄露 | 只读消费 | 不发写入权限（与现有 share/edit 语义隔离） |
| 用户从不打卡 | badges 空 | 空态引导文案（不强制） |

### 4.4 优点 / 风险
- ✅ 给追踪加"正反馈"，提升行中活跃（MonkeyTravel 2026 竞争实证：行业共识"live 是差异化"）
- ✅ 徽章是纯规则，可测试、可解释、不消耗 LLM
- ⚠ 比 A 多一张表 + 一个 hook，成本略高；徽章需要运营维护（别沦为"打卡机器"）

---

## 5. 晒图路线 C — 朋友圈/小红书"旅程高光卡"（内容工厂升级）

> 现状：`generate_xhs_note` 只有"出发前攻略"一个模板 + LLM 润色；缺"行中/行后"真实数据素材。
> 做法：把晒图升级为**"数据驱动的旅程故事生成器"**，仍是"内容工厂 + 手动复制"，不接公域发布 API。

### 5.1 数据流

```
journey projection + passport badges + expenses + bookings
   │  TripStoryAgent（新 PipelineStep：LLM 主路径，模板兜底）
   ▼
trip_story：{ title, body(正文), highlights[], stats{...}, badges[], social_topics[] }
   │  前端"生成故事卡" → 编辑 → 复制
   ▼
选择渠道：朋友圈（纯文本/卡片）/ 小红书（标题+正文+话题）/ 通用长图（HTML 卡片）
```

### 5.2 三类产物（同一份数据，三种模板）
| 渠道 | 形态 | 数据来源 |
|---|---|---|
| 小红书 | 标题 + 正文 + 话题（复用 XhsNoteDialog） | journey.projection + badges |
| 朋友圈 | 短文案 + 行程封面卡（HTML/CSS 渲染成图片，可长按保存/截图） | journey.projection + 头图（已有分享头图资产） |
| 通用长图 | "足迹榜 + 账单 + 徽章墙 + 时间线"一图流（HTML 导出 PNG） | projection + passport + expenses |

- **模板兜底**（LLM 失败不空白）：基于投影的规则文案，如"Day1 落地杭州，走了 3 站，花了 268 元，打卡 2 个景点；Day2 灵隐寺…"
- **图片生成**：先做"HTML 卡片 → 浏览器截图/导出"（复用现有 headless 截图能力），不做服务端 SVG 拼图引擎（避免多一层复杂度）；PWA 下用户可直接截图保存
- **晒图不造假**：所有数据都来自已记录事件；未打卡的不推断；文案标注"行程数据来自你的打卡/记账"

### 5.3 涉及文件
- `backend/app/services/trip_story_service.py`（新增：投影 → 故事；LLM 主路径 + 模板兜底，与 xhs_service 同构）
- `backend/app/agent/pipeline.py`：注册 `StoryStep`（行中/行后触发）
- `backend/app/schemas/story.py`：TripStoryOut / StoryCardSpec
- `backend/app/api/v1/trips_story.py`：POST /trips/{id}/story
- `frontend/src/components/StoryCardGenerator.vue`（新增：渠道选择 + 编辑 + 复制 + 长图预览）
- `frontend/src/locales/{zh-CN,en-US}.js`

### 5.4 故障模式
| 故障 | 检测 | 恢复 |
|---|---|---|
| LLM 文案失败 | 抛出 | 模板兜底（复用 xhs 哲学，source 标注 template） |
| 投影为空（无打卡） | 数据量检查 | 引导"先记一笔/打一次卡"，不硬生成 |
| HTML 卡片导出失败 | 渲染异常 | 回退纯文本 + 复制；标注"图片导出暂不可用" |
| 内容含 PII（人名/凭证号） | 模板过滤 + schema 白名单 | 晒图只输出 name/金额/日期，凭证号绝不进文案 |

### 5.5 优点 / 风险
- ✅ 把"行中真实数据"变成晒图素材——这是 OTA/预订玩家不支持、规划层独占的护城河
- ✅ 复用 xhs_service 的降级链（LLM → 模板），成本低
- ⚠ "长图导出"若做服务端渲染有额外链路；先用前端截图保底
- ⚠ 晒图吸引力完全依赖用户打卡习惯——需与追踪 A/B 联动（先有追踪，才有故事）

---

## 6. 三方案组合关系

```
预订打通（booking-schemes.md A/B/C）  ← 提供 confirmed 订单（Train_Goer/Hotel_Stayer 徽章 + 行中凭证）
        │
追踪路线 A（轻量时间轴）  ← 复用 TripEvent 投影（最低成本先做）
        │
追踪路线 B（护照徽章）  ← 在 A 之上加激励层（第二优先）
        │
晒图路线 C（旅程高光卡）  ← 依赖 A/B 的数据沉淀（联动出圈）
```

**依赖心智**：先有价值数据（事件流）→ 再沉淀（时间轴/护照）→ 最后出圈（晒图）。三者不是并列任务，而是递进管线。

---

## 7. 推荐排序（评审）

| 优先级 | 路线 | 理由 |
|---|---|---|
| P0 | 追踪 A 轻量时间轴 | 零新表、复用现有事件流，1-2 天可落地，解锁全部下游 |
| P1 | 追踪 B 护照徽章 | 复用 A 的投影 + 事件 hook，激励层价值高 |
| P1 | 晒图 C 高光卡（模板先行） | 依赖 A 数据；"朋友圈晒图"需求直接回答 |
| P2 | 预订打通（选 A outlink） | 给故事卡补充"已订凭证"真实素材（可后置） |

> 与预订方案是双向增强：预订 confirmed 事件 → 徽章/故事素材；追踪沉淀 → 预订方案更有"订单回填"动力。

---

## 8. 风险与开放问题

| # | 开放问题 | 影响 | 建议 |
|---|---|---|---|
| 1 | 用户不打卡怎么办 | 追踪/晒图数据空 | UI 引导 + 徽章激励；不硬造数据 |
| 2 | HTML 卡片导出长图的跨端一致性 | 晒图质量 | 先用截图保底，服务端渲染后置 |
| 3 | 晒图内容是否允许含金额 | 敏感度 | 默认可含金额（炫耀点），提供开关 |
| 4 | 护照徽章是否需要运营配置 | 规则库维护 | 版本化 + 测试覆盖，暂不做后台管理 |

---

*关联阅读：docs/articles/13-trust-gap.md（第一次尝试=产品问题）· docs/night-build-todo.md（行中/协作/导入迭代脉络）*