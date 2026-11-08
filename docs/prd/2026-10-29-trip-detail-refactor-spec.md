# 迭代需求规格：TripDetailView 重构（信息架构 + 埋点基线）

**Status**: Draft（方案未出，判定线与事件契约已三方拍板）
**Author**: Alex (PM)  **Last Updated**: 2026-10-29  **Version**: 0.2
**Stakeholders**: 彭军（owner）· mult-ai-ach（架构/开发）· cpo（裁决）· code-review（埋点审计）

> 本文档只收口**已拍板**的部分：判定线、事件契约、范围与非目标、灰度与回看计划。
> Solution 部分（组件树 / 显隐规则 / 交互动线）待 @mult-ai-ach 方案输出后补齐。

---

## 1. Problem Statement（问题陈述）

`TripDetailView.vue`（1637 行 / 76KB）一个页面同时服务三个用户时机（planning 规划 / 行前 / live 行中），全部线性堆在一个滚动流里：
- 10 个 CollapsibleSection 三组工具箱，首屏被次级功能挤压，核心内容（地图+逐日行程）靠滚动才可见
- 操作点分散在 4 个层级，合计 20+ 可点目标，无主次
- 近期新增组件（BookingPanel / JourneyTimeline / PassportPanel / StoryCardGenerator）继续堆在同一滚动流，拥挤在加剧

**不解决的代价**：行中用户（差异化护城河）在半路上找不到「今天去哪」；Tab 收纳若失败（用户找不到工具）没有数据能证明，只能靠感觉回滚。

---

## 2. Goals & Success Metrics（判定线，回看基准）

| # | Goal | 判定线 Metric | 数据源 | 阈值 |
|---|------|--------------|--------|------|
| G1 | 规划工具不因收纳而流失 | 单工具打开次数（AI修订/PlanB/质检/批量生成）vs 重构前基线 | 埋点 intent 事件 | 单工具跌幅 >30% → 撤回或重做评审 |
| G2 | 逐日行程首屏可见 | 首屏可见占比 + 25/50/75% 滚动深度 | 埋点 exposure 事件 | 目标 ≥ 基线 +20pp |
| G3 | 核心操作完成率不跌 | 打卡/顺延/跳过/加站 成功事件 | **后端 TripEvent 事实流**（不新增埋点） | 不跌 |
| G4 | 行中单点操作完成率不跌（单列） | 行中会话内 打卡/顺延/跳过 成功事件数 | 后端 TripEvent 事实流 | 单独阈值，不与 G3 混平均 |
| G5 | 主操作收口可判定 | 顶栏 编辑/问AI/分享 点击分布 | 埋点 intent 事件 | 有分母，三层结构可对比 |

> 分层视角（code-review 约束）：G2/G5 按 viewport 宽度 + touch 分层回看，防灰度期设备结构变化制造假象。

---

## 3. 事件契约（前端意图埋点，阶段一交付）

### 3.1 原则（三方拍板）
- **不引第三方 SDK**；新建 `src/api/modules/analytics.js` 导出 `trackEvent(name, payload)`，`api/index.js` 加一行 export（code-review 约束：不碰 `modules/events.js`——那是行程事件流，语义撞车）
- 后端事实流与前端意图分离：**完成率类判定线直接读 TripEvent（既有事实源：check/skip/delay/edit 事件已全量入账，journey_service 已有投影能力），前端埋点只发意图与曝光**——不做重复写入，口径更硬，埋点面减半
- 挂载点复用 `useTripDetailLoad.js`（load 完成 + IntersectionObserver），不在 TripDetailView 开新逻辑

### 3.2 意图侧事件（全部新埋点）

公共载荷（所有事件必带）：`trip_id` · `trip_phase`（planning/live/finished）· `viewport_width` · `is_touch` · `role`（owner / guest）

| 事件 | 触发时机 | 专有载荷 | 服务判定线 |
|------|---------|---------|-----------|
| `planning_tool_open` | 点击规划工具（click 时发） | `tool`: `ai_revise` / `plan_b` / `qa` / `batch_gen` | G1 |
| `top_action_click` | 顶栏主操作（click 时发） | `action`: `edit` / `ask_ai` / `share` | G5 |
| `itinerary_first_view` | load 完成，IntersectionObserver 查逐日行程 | `visible`: bool | G2 |
| `itinerary_scroll_depth` | 滚动经过 25% / 50% / 75% | `depth`: 25/50/75 | G2 |

- **不发完成率类事件**（打卡/顺延/跳过/加站）——判定线从 TripEvent 投影，见 3.1
- guest 角色（share 页免登录）V1 只透传 role 标记，不单独扩意图事件；其操作已有 TripEvent 记录，判定线口径 owner 端优先
- 具体口径（如「行中会话」定义、success event / session 比率）在 Solution 文档中定，回看时按既定口径执行

---

## 4. 时机规则（cpo 裁决，已锁死）

| phase | 首屏 | 次级 |
|-------|------|------|
| planning | 地图 + 逐日时间线 | 规划工具箱（AI修订/PlanB/质检/批量生成）全部收 Tab 第二屏 |
| live | 今日视图（自动定位当日）+ 打卡/追踪入口 | **隐藏 AI 修订入口**，只留「更多」里「快速改行程」；JourneyTimeline / PassportPanel / StoryCardGenerator 归行中 |
| 行前 | BookingPanel 按入住前 48h 自动浮现。**基准 = 首个 `stop_type==hotel` 站点的日期**（day_number → start_date 偏移；与 booking_service 选酒店实体的规则同源）；无 hotel 站点兜底 = 行程 start_date 前 48h。~~plan.checkin~~ **不用作基准**——它是入住指引产物（dict），不是日期字段（servicing_service 实证） | 不靠用户自己找 |

- 主操作三件套随状态换血：planning = 编辑/问AI/分享；live = 打卡/追踪/分享。**永远 ≤3 是硬约束**
- 四件套去处（cpo 定）：BookingPanel=行前，JourneyTimeline/PassportPanel/StoryCardGenerator=行中，**不混进 planning Tab 第二屏**

### 4.1 实现期偏差登记（2026-11 收口，代码为准）

实现过程中有 6 处与上表不同，均为实现期判断，此处登记以免下次按 PRD 字面「纠错」：

| # | 偏差 | 理由 |
|---|---|---|
| 1 | `HotelRecommend` 同时出现在**规划**与**行前**两个 tab | `plan.hotels` 是规划产物，规划完就想看候选；只放行前会错过时机 |
| 2 | 「更多 → 调整行程」在**所有非规划时机**可用（PRD 只写了 live） | 行前同样要改行程；且 AI 修订卡已提升到主路径常驻，不存在「收起来就找不到」 |
| 3 | **未做 sticky 顶部导航级联**：详情页头部在 ≥721px 吸附 | 依赖 `App.vue` 把 `.app-main` 的 `overflow` 显式设 `visible`（el-main 默认 auto 会令子孙 sticky 退化为静态位移）；移动端头部两行不吸附 |
| 4 | 折叠记忆键升到 `tripDetail.aux.v2.*` | 旧键记录的是 12 区平铺时代的展开态，面板换分组后继承会误导 |
| 5 | **finished 独立「回顾」tab**（PRD 未定义第四态） | 行程结束后挂「行中」语义不成立；回顾组 = 追踪/护照/故事/**事件流** |
| 6 | **prep 给两个 tab**（行前 + 规划，默认停行前） | 质检/时间校验在行前同样要看，旧路径需「更多 → 调整行程」两跳 |
| 7 | **百分比灰度（20% → 100%）降级不做** | 当前流量不足以形成统计显著，`percent` 只会制造「以为灰了其实没灰」的假象。灰度改为：服务端 kill switch（`FEATURE_FLAGS_JSON`，改 env + 重启即全站回滚，不用重发前端）+ 设计伙伴 `?flag=` 抽样对照。判定线回看仍按 §2 执行 |

---

## 5. Non-Goals（范围锁死）

- **不做品牌级视觉改版**：审美升级只做 token 层（卡片化、间距/圆角、hero 真实封面），不动配色系统与字体；任何「顺便升级配色」诉求走变更请求流程单独立项
- 不引第三方分析 SDK（posthog/mixpanel/gtag 等）
- 重构期间（阶段二灰度前）**冻结行中交互新功能立项**，避免与收纳设计打架
- 阶段一不做交互改动（纯组件拆分，可逆）
- 不做移动端原生独立设计（移动断点已存在，本次只做收纳与浮现规则适配）

---

## 6. 灰度与回看计划（两步走，各步回看）

**阶段一（预计 1 周）——纯拆分 + 埋点**
- TripDetailView 瘦身为 orchestrator，组件拆分不动交互
- 上线 4 类意图埋点 + `POST /api/events` 端点
- **完成定义 = 埋点上线并开始积累基线**（无埋点 = 阶段未完成，code-review 缺口）
- 回看点：基线起量、事件无异常、前端 build/后端测试全绿

**阶段二（预计 1-2 周）——信息架构调整（大赌注）**
- 按 §4 时机规则动交互：Tab 收纳、首屏重构、三件套换血
- 灰度顺序：先组内/设计伙伴 → 20% → 100%（Feature Flag）
  - **2026-11 降级**：百分比灰度不做（流量不足以统计显著），改为服务端 kill switch 全站开关 + 设计伙伴 `?flag=` 抽样对照，见 §4.1-7
- 上线后 14 天出判定线数据（G1-G5），超阈值进「撤回或重做」评审，cpo 裁决

**回看 ownership**: Alex (PM) —— 阶段一基线起量核验、阶段二 14 天判定线数据与结论；数据结论在评审会前 48h 同步全员（意外=失败，不搞突然袭击）

---

## 7. 机会成本（本周期 2-3 周产能竞争项）

| 排队项 | 处置 | 理由 |
|--------|------|------|
| 未合并分支收尾：share-gate / price-realism / open-hours-real（10-28 夜分支） | **不推迟** | 夜间流水线照常，与重构正交 |
| ShareView 受邀编辑拖拽接线（map-drag-edit 遗留） | **穿插** | 阶段一收尾窗口顺手做 |
| escalation 前端提示条 + rating 前端控件 | **推迟 2 周** | 后端已就绪仅前端接线，低压无数据风险 |
| 新的行中功能立项 | **冻结** | 与阶段二收纳设计冲突 |

---

## 8. Open Questions（Solution 阶段必须回答）

- [ ] 组件树与显隐规则表（@mult-ai-ach 方案文档）——Owner: mult-ai-ach
- [ ] 完成率口径定义（行中会话 / success-per-session）——Owner: Alex (PM)，回看前定死
- [ ] `POST /api/events` 的限流/防滥用面（与既有 API 同纪律）——Owner: code-review
- [ ] 阶段一拆分边界的可回滚点（每组件独立 commit？）——Owner: mult-ai-ach