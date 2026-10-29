# Solution：TripDetailView 重构 — 组件树 / 显隐规则 / 回滚边界

**Status**: Draft v0.1（对齐 PRD `docs/prd/2026-10-29-trip-detail-refactor-spec.md` v0.2）
**Author**: mult-ai-ach  **Date**: 2026-10-29
**对应 Open Questions**: 组件树与显隐规则表 ✅（本文档）· 阶段一拆分可回滚点 ✅（§5）· 完成率口径（PM）· events 限流（code-review）待各自产出

---

## 0. 现状核对（已读代码确认）

- `TripDetailView.vue` 1637 行 / 76KB，内部区块：`topbar` → `hero-bar` → `live-card`（全宽置顶）→ `detail-layout`（`main-col`: map-card + N × day-card；`side-col`: TripDashboard）→ 3 组 `toolbox-group`（规划修订 / 旅程执行 / 装备素材，共 10 个 CollapsibleSection）→ `bottom-bar` + 5 个对话框（xhs / import / genDays / shareSettings / editDialog）
- `CollapsibleSection` 已支持 `forceOpen`，**但 TripDetailView 未透传**：`exportAll` 状态被 `withExportAll` 置位却无消费方（grep `exportAll` 仅 script 4 处定义，模板 0 处；`forceOpen` 引用 0 处）
  - **含义**：现在截图/PDF 导出**并未**展开默认收起的折叠区（revision/planB/qa/events 等默认 closed 的内容可能不落在导出图里）。阶段一纯拆分不改语义，但阶段二 Tab 收纳后导出问题会放大 —— 必须在阶段二补「导出模式 = 渲染全部内容」的接线（见 §5.3）
- 前端**无 Feature Flag 基建**（grep `FeatureFlag|useFlag|flags` 为 0）→ 阶段二灰度需要一个最小 flag 模块（§5.2）
- `src/api/modules/events.js` 已属行程事件流 → 埋点走新模块 `analytics.js`（code-review 约束，确认无冲突）

---

## 1. 阶段一：纯拆分（1 周，含埋点）

### 1.1 组件树（物理拆分，交互零改动）

拆分原则：**按现有 DOM 区块切**，props/emits 契约 = 当前模板绑定原样搬移；TripDetailView 收敛为 orchestrator（装配 + 共享状态 + 对话框）。

| 新组件（`src/components/trip-detail/`） | 承载的现有区块 | 主要 props | 主要 emits |
|---|---|---|---|
| `TripDetailTopBar.vue` | `topbar`（back / 编辑 / 问AI / 分享 / 更多） | trip, sharing, isFavorite, favoriting, hasSharedToken | ask-ai, share, more(cmd), back |
| `TripDetailHero.vue` | `hero-bar`（封面 / 标题 / 状态徽标+切换 / meta pills） | trip, statusMap, statusUpdating, tripTypeDisplay | edit-open, status-change |
| `TripDetailLiveToday.vue` | `live-card`（今日视图中全宽置顶块） | live, liveOp, typeEmoji, typeLabel | check, skip, delay |
| `TripDetailMapCard.vue` | `map-card`（地图 + drag error + activeDay） | markers, activeDay, canMapDrag, mapDragError | clear-focus, map-move |
| `TripDetailDayCard.vue` | `day-section` 单个（日头 + stops 时间轴 + 空态） | day, activeDay, typeEmoji, typeColor, typeLabel, dayIndex | focus-day, add-stop, day-cmd, stop-cmd, stop-edit |
| `TripDetailToolbox.vue` | 3 组 `toolbox-group`（10 个 CollapsibleSection 的编排容器；阶段一保持 3 组结构与各自 default-open 不变） | trip, plan, planB, budget…（经 orchestrator 透传） | revise, plan-change, …（各子件原发出） |
| `TripDetailSidebar.vue` | `side-col`（TripDashboard） | tripId, budget, budgetPercent, basisText, tripBudget, travelers | — |
| `TripDetailBottomBar.vue` | `bottom-bar`（加天 / 批量生成 / 导出 split） | exporting | add-day, gen-days, export(cmd) |
| `TripDetailDialogs.vue` | 5 个对话框（xhs / import / genDays / shareSettings / edit 三合一） | 同现状绑定 | imported, saved, deleted（向上透传） |

共享逻辑不动：`useTripDetailLoad` / `useRevise` / `useEditDialog` / `useTripShareActions` / `useExport` 全部留在 orchestrator 装配层，组件只接 props/emits —— **状态所有权不变，是「可回滚」的地基**。

### 1.2 埋点（阶段一交付，见 §4）

---

## 2. 阶段二：信息架构（1–2 周，Feature Flag 灰度）

### 2.1 页面结构（三时机，单编排）

```
TopBar（三件套随状态换血，≤3 硬约束）
Hero（token 层升级：真实封面占位升级、间距/圆角统一）
├─ live? → LiveToday 置顶（自动定位当日，行中生命线）
├─ 主内容：MapCard + 逐日 DayCard 时间线（首屏绝对权重）
├─ 次级内容 Tab（按时机只出现该出现的 Tab）：
│   planning → Tab「规划」：AI修订 / PlanB / TimeGate / 质检 / 批量生成
│   行前     → Tab「行前」：BookingPanel(浮现) / 酒店 / 服务层 / 行李 / 事件
│   live     → Tab「行中」：JourneyTimeline / PassportPanel / StoryCardGenerator
└─ BottomBar（移动端 sticky；桌面上移到 TopBar 区）
```

### 2.2 显隐规则表（cpo 分组落地；「酌情处理」= 不允许）

| 组件/块 | planning | 行前（T-48h 起） | live | finished | 备注 |
|---|---|---|---|---|---|
| MapCard + DayCard 时间线 | 首屏常驻 | 首屏常驻 | 首屏（折叠到「查看全行程」下方） | 首屏常驻 | 核心主路径，任何时机不消失 |
| LiveToday 今日视图 | — | — | 全宽置顶，默认展开 | — | 行中 G4 生命线 |
| 规划工具箱（AI修订/PlanB/TimeGate/质检/批量生成） | Tab「规划」 | 隐藏 | **隐藏**（AI 修订收「更多 → 快速改行程」） | 隐藏 | AI修订 live 隐藏 = cpo 裁决 |
| BookingPanel | — | **自动浮现**：入住前 48h 置顶（checkin 日 = plan.checkin 最早日；无 checkin 数据 → trip.start_date 前 1 天兜底） | —（行中不再变化） | 隐藏 | 不靠用户找 |
| HotelRecommend / TripServicing / PackingList / TripEventFeed | — | Tab「行前」 | — | — | 服务层与行李同组 |
| JourneyTimeline | — | — | Tab「行中」（打卡后自动刷新） | Tab「行中」 | cpo 归类：行中 |
| PassportPanel / StoryCardGenerator | — | — | Tab「行中」 | Tab「行中」 | 同上 |
| 主操作三件套 | 编辑 / 问AI / 分享 | 编辑 / 分享 / 导出 | **打卡 / 追踪 / 分享** | 分享 / 编辑 / 导出 | 换血方案：live 时「打卡」= 滚动到今日视图并高亮，「追踪」= JourneyTimeline 展开 |
| 更多（More） | 收藏/导入/画廊/XHS/分享设置/受邀编辑/删除 | 同左 | 同左 +「快速改行程」（仅此一处 AI 修订入口） | 同左 | 低频/危险动作收纳不变 |

> 行前 prompt 的「T-48h」是默认值；`plan.checkin` 数据模型确认后由 PM 在回看口径里复核（若 checkin 缺失率高，改为「行程开始前 48h」单基准）。

### 2.3 交互细节（阶段二范围）

- 移动端：BottomBar sticky 常驻（加天 / 打卡 / 导出按时机换血）；站点行操作 hover 浮现仅桌面，移动端收敛为点按停留菜单
- Tab 收纳防「工具找不到」：规划 Tab 首次进入给 1 次轻提示（tooltip 定位），不弹教学
- 导出模式：`withExportAll` 改为「切换为导出渲染态」（Tab 全显、CollapsibleSection forceOpen 全展开、LiveToday 并入），截图/PDF 与旧版一致 —— **修复 §0 发现的 forceOpen 未接线问题**

---

## 3. 阶段一完成定义（对齐 PM 验收）

1. 9 个组件 + orchestrator 拆分落地，`npm run build` 绿，后端 629 测试绿
2. **埋点上线并开始积累基线**（analytics 模块 + `POST /api/v1/analytics/events` 端点）
3. 基线起量核验（PM 出数据结论：无异常事件、四事件都有量）

## 4. 事件契约（对齐 spec §3，权限/口径细节）

**前端**：`src/api/modules/analytics.js` 导出 `trackEvent(name, payload)`；fire-and-forget（`fetch keepalive`，失败静默不重试）；`src/api/index.js` 加一行 export。

| 事件 | 挂载点 | 专有载荷 |
|---|---|---|
| `planning_tool_open` | 各规划工具点击（click 时发，勿等结果） | tool: ai_revise / plan_b / qa / batch_gen |
| `top_action_click` | 顶栏三件套点击 | action: edit / ask_ai / share |
| `itinerary_first_view` | `useTripDetailLoad.load()` 完成后，IntersectionObserver 查逐日时间线首节点 | visible: bool |
| `itinerary_scroll_depth` | 滚动深度 >25/50/75%（一次性触发 + 节流） | depth: 25/50/75 |

公共载荷：trip_id · trip_phase · viewport_width · is_touch · role（owner/guest）。
完成率类事件**不埋**（打卡/顺延/跳过/加站走 TripEvent 事实流投影，PM 已拍）。
后端端点：新 router `backend/app/api/v1/analytics.py`（注册进 `api/v1/__init__.py`），schema 白名单校验 + 每 session 限频（细节归 code-review）。

## 5. 回滚边界

### 5.1 阶段一（每组件独立 commit）
- 拆分顺序：TopBar → Hero → LiveToday → MapCard → DayCard → Toolbox → Sidebar → BottomBar → Dialogs，**一组件一 commit**，每个 commit 后 `npm run build` + 后端 pytest 绿
- 回滚 = `git revert <commit>`，零依赖（组件间无交叉依赖，state 全在 orchestrator）
- 回归手段：现功能手测清单（分享/导出/live 操作/编辑三合一逐个过）；不做截图像素 diff（成本不值）

### 5.2 阶段二（Feature Flag）
- 新最小模块 `src/utils/flags.js`（localStorage 持久 + `?flag=` URL 覆盖，无后端）
- flag：`tripDetail.ia.v2`；灰度 组内 → 20% → 100%
- **编排层双模板**：v1 组合（阶段一产物）与 v2 组合（Tab 结构）并存于 orchestrator，flag 决定渲染哪套；**flag off 时埋点照常发** → 对照组天然成立，G1–G5 真有分母
- 回滚 = flip flag off，瞬回 v1，无数据迁移、无状态残留；组件文件一个不删

### 5.3 导出模式（跨阶段）
- 阶段二必须把 `exportAll` 接到 `CollapsibleSection.forceOpen` 并覆盖 Tab 结构；此接线属于「恢复既有导出语义 + 适配新结构」，不属于交互改版，不占 Non-Goal 指标

---

## 6. 风险与依赖

- **G1 最大风险是 Tab 收纳本身**（PM 早就标注）：缓解 = flag off 对照组 + 规划 Tab 轻提示 + 回看线超阈值即「撤回或重做」
- 依赖 PM/code-review：完成率口径定义、`/events` 限流方案 —— 阶段一埋点代码不依赖这两项（意图/曝光事件先行），不阻塞
- 依赖确认：行前 Tab「T-48h」基准值、live 三件套「打卡/追踪」按钮语义（我按「滚动定位+展开」实现，若产品要求进入独立全屏视图，改动局限在 TopBar 组件内）