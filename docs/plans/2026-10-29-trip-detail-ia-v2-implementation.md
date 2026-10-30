# 实施记录：TripDetailView 信息架构 v2（阶段二）

**Date**: 2026-10-29  **Branch**: `nightly/2026-10-29/7-task-trip-detail-refactor`
**依据**: `docs/prd/2026-10-29-trip-detail-refactor-spec.md` v0.2 §4 时机规则 · `docs/plans/2026-10-29-trip-detail-refactor-solution.md` §2 阶段二
**状态**: 已实现并本地验证（构建 + 693 后端测试 + 三时机真机截图）

---

## 1. 问题（用户诉求：展示与交互杂乱）

阶段一拆分只做了物理拆组件，版面仍是线性堆叠。核对现状后确认四个结构性噪声源：

| # | 问题 | 量化 |
|---|---|---|
| 1 | 12 个 `CollapsibleSection` 平铺在同一条滚动流 | 收起态也是 12 行折叠头（≈480px 纯标题），核心内容被次级功能淹没 |
| 2 | 页面开头 TopBar + Hero 双行信息 | 约 200px 才见到地图；同屏 5 个操作按钮 + 6 个 meta pill |
| 3 | 同一信息两个控件 | Hero 里「状态徽标」+「状态下拉框」并排显示同一个 status |
| 4 | 主次同权重、全程展开 | 逐日卡默认全开，10 天行程 = 10 屏 |

历史包袱：`0cd77db` 曾做过 4-tab 工作台，`470a9d3` 又回退成三段式平铺（提交说明：replace 4-tab layout with three-section workbench）。**两次都失败的根因是「把主路径塞进了 tab」或「干脆不平铺不分层」**。

## 2. 方案要点（与两次前作的差别）

**主路径永不进 tab，只收纳次级工具。**

```
Header（合并 TopBar+Hero，一行体系，主操作 ≤3 按时机换血）
├─ live? LiveToday 置顶
├─ 主路径：MapCard + 逐日大纲（可折叠，只展开当天/第一天）
│    └─ 日程操作条（加天 / 批量生成 / 导出）
└─ 工作台 Workspace（单卡容器）
     ├─ 时机 tab：规划 / 行前 / 行中（徽标：质检问题数 / 预订状态 / 打卡进度）
     └─ 「全部工具」开关（导出模式下自动全开）
侧栏：仪表盘（预算 / 追踪），sticky 不变
```

关键设计决策：

1. **时机四态**（`planning / prep / live / finished`）：埋点仍用三态 `tripPhase`，基线口径不漂移；`prep` 锚点按 PRD §4 = 首个 `hotel` 站点所在日 −48h，无 hotel 站点则 `start_date −48h`。
2. **收敛为单一控件**：状态徽标 + 下拉合并成一个可点 chip（点开选状态）。
3. **元信息降噪**：6 个 pill → 一行带 `·` 分隔的文本流（信息量不变，视觉噪音大幅下降）。
4. **逐日折叠**：收起态给「N 站 · ¥花费 · 时长」一行摘要，展开是主操作；地图聚焦降级为独立图标按钮（避免「点日期头 = 跳到地图」这个反直觉主操作）。
5. **导出口径修复**：`exportAll` 真正接到 `forceOpen` + tab 全显 + 日程全展开（阶段一遗留的「导出抓不到收起内容」bug）。

## 3. 与 PRD/Solution 的偏差（4 条，均为实现期判断）

| # | 偏差 | 理由 |
|---|---|---|
| 1 | `HotelRecommend` 同时出现在**规划**与行前 tab | PRD 把酒店归行前，但 `plan.hotels` 是规划产物，规划完立刻就想看候选；藏在行前会失去时机 |
| 2 | 「更多 → 调整行程」在**所有非规划时机**可用（PRD 只写了 live） | 行前用户同样需要改行程；否则规划工具一收就彻底消失（G1 判定线最大的风险正是这个） |
| 3 | **未做 sticky 头部** | 见 §5：`.el-main` 是 `overflow:auto` 却不滚动的祖先，`position: sticky` 在它内部只产生静态位移（实测压住行中卡片 / 或直接跟页面滚走）。要修需改全局 `.app-main{overflow:visible}`，影响面超出本次范围 |
| 4 | 折叠记忆键升到 `tripDetail.aux.v2.*` | 旧键记录的是 12 区平铺时代的展开态；面板换分组后继承会误导（实测：行前 tab 里「预订」因旧记忆默认收起，与「不靠用户自己找」相悖） |

## 4. 文件变更

**新增**
- `frontend/src/utils/flags.js` — 最小 feature flag（URL `?flag=tripDetail.ia.v2=off` → localStorage → 默认值），失败静默
- `frontend/src/utils/tripPhase.js` — `detailPhase()` 四态 + `prepAnchorDate()` + `currentDayNumber()`
- `frontend/src/components/trip-detail/TripDetailHeader.vue` — 合并头部（状态 chip / 时机主操作 / 元信息流）
- `frontend/src/components/trip-detail/TripDetailMoreMenu.vue` — 「更多」菜单（含 `adjust` 唯一 AI 修订入口）
- `frontend/src/components/trip-detail/TripDetailWorkspace.vue` — 工作台容器（tab + 全部工具开关 + 徽标）

**改造**
- `TripDetailToolbox.vue` — 新增 `keys`（面板白名单，`null`=全部）与 `flat`（嵌卡内：去分组标题/虚线、隐藏子面板重复标题与状态标签）
- `TripDetailDayCard.vue` — 折叠 + 摘要 + 主操作换位（展开 vs 地图聚焦）
- `TripDetailView.vue` — 编排 v2：时机 → tab、逐日默认展开集、header 操作分派、`wsKeys`、导出全开

**删除**
- `TripDetailTopBar.vue` / `TripDetailHero.vue`（内容并入 Header，git 历史可回滚）

**i18n**：`tripDetail.tabs` 改为 `plan/prep/live`，新增 13 键；zh/en 各 213 键，脚本校验零差异。

## 5. 踩坑记录（留给后续）

1. **sticky 陷阱**：Element Plus `.el-main` 默认 `overflow:auto` 但页面滚动在 `document` 上 → 子孙 `position: sticky` 会「静态下移」并覆盖后续内容。实测数据：`top:64` 时头部 top 从 96 变 160、行中卡片 top 182 被压住；`top:0` 时滚 600px 头部跑到 -504（完全不吸附）。结论：详情页头部不做 sticky，除非先改全局 `.app-main`。
2. **同屏两个 ¥ 数字**：「行程大纲」曾显示站点合计 ¥2502，侧栏预算 ¥3214（含往返交通）。同一屏两个金额是纯噪音 → 大纲只保留「天 / 站」，花费统一由侧栏预算明细承载。
3. **嵌套标题重复**：`CollapsibleSection` 标题 + 面板自带 header（预订/旅程追踪/护照/故事卡）双写标题。`flat` 模式下按面板逐个去重：只有标题+？的整行隐藏，带状态标签的保留标签靠右。
4. **JWT 本地联调**：`JWT_SECRET` 未配置时是**进程级随机**密钥，外部脚本签发的 token 一定校验失败（`token_invalid`）。本地要造 token 必须让服务与脚本共用同一个 `JWT_SECRET`。

## 6. 验证证据

- `cd frontend && npm run build` → ✓ built in 4.28s
- `backend/.venv/bin/python -m pytest tests/ -q` → **693 passed**（117s）
- 真机（localhost:5173 接 8090 后端）三时机截图核对：
  - 行中（大理 10-27~10-29）：Header 主操作 = 追踪/分享/打卡；LiveToday 置顶；工作台「行中 2/11」= 追踪/护照/故事卡；逐日默认只展开当天
  - 行前（厦门 start 明日）：Header = 编辑/问AI/分享；工作台「行前」= 预订(默认展开)/打包/行程服务/住宿/动态
  - 规划（厦门 start 11-20）：工作台「规划 5」= AI 调整/备选/质检/住宿；D1 默认展开
  - 交互实测：单日折叠切换 ✓、展开/收起全部 ✓（按钮文案随之切换）、「全部工具」→ 11 个面板 + 分组标题回归 ✓、「更多 → 调整行程」→ tab 变 `行中|规划` 并出现修订输入框 ✓
  - 移动端 375×812：无横向溢出 ✓，Header 折成「标题/元信息 + 图标操作行」✓
  - i18n 裸键扫描：`[]`（无残留 `tripDetail.*` 直出）

## 7. 回滚

- IA 分组：`?flag=tripDetail.ia.v2=off`（或 localStorage `mtp.flag.tripDetail.ia.v2=0`）→ 工作台退回「12 面板分组平铺」，用于 G1 工具流失对照组
- 版面/头部/折叠：`git revert` 本分支提交（组件文件独立，无数据迁移、无状态残留）

## 8. 未做（下一窗口）

- `sticky` 头部：~~需先评估把 `.app-main` 的 `overflow` 改 `visible` 对其他视图的影响~~ → 已在 §9 恢复
- G1–G5 判定线：埋点仍在（`planning_tool_open` / `top_action_click` / `itinerary_first_view` / `itinerary_scroll_depth`），tab 收纳后的工具打开率需上线 14 天取数
- `docs/plans/...-solution.md` §2.1 文字描述的是已废弃的 4-tab 方案，本文档为准

---

## 9. 补充：规划工具提升到主路径（2026-10-29 晚，用户反馈驱动）

**用户原话**：「规划修订和行程备选方案应该放在行程地图和行程大纲之间，这样操作起来比较方便」

### 9.1 改动

| 项 | 内容 |
|---|---|
| 新增 | `components/trip-detail/TripDetailPlanTools.vue` — 单卡两段：AI 调整行程（输入 + 状态/diff/质检）+ 行程备选方案（主/备 segmented + 差异对比） |
| 位置 | `main-col` 内：MapCard → **PlanTools** → 行程大纲标题行 → DayCard… |
| 显隐 | `planToolsVisible = iaV2 && !exportAll && (phase==='planning' \|\| wsPlanExtra)`，与工作台时机规则一致；导出时卸载（导出物不该出现输入框） |
| 去重 | `TripDetailToolbox` 新增 `hoistedKeys`，`revise`/`planb` 传 `['revise','planb']` → 工具箱（含「全部工具」模式）不再渲染这两个面板 |
| 灰度 | flag off 时 `hoistedKeys=[]` + 不渲染 PlanTools → 修订/备选回到工具箱，G1 对照组成立（已实测） |
| 埋点 | `tool-open` 仍发 `ai_revise` / `plan_b`（`@click.capture` 覆盖整个修订块，切换备选时发 `plan_b`） |
| 滚动 | 「更多 → 调整行程」改为滚到 `.plan-tools` |

### 9.2 同时修掉的三个真 bug

1. **备选方案点了没反应**：`useTripDetailLoad.onPlanChange` 只处理「切回主案」的重载，**从未写入 `activePlan`** → segmented 永远停在「当前行程」。旧版藏在工作台折叠面板里，被「折叠=没打开」掩盖。修复：`activePlan.value = p`，切回主案时才 `load()`。
2. **滚动落点压在导航下**：`scrollIntoView({block:'start'})` 忽略 sticky 导航（64/56px），目标顶到视口 0 点被遮。统一替换为 `scrollToEl()` 手算偏移，并对条件渲染的目标轮询等待（最多 1s）——固定 `setTimeout(40)` 在慢设备上滚到空气。
3. **sticky 头部恢复**：`App.vue` 的 `.app-main` 显式 `overflow: visible`（el-main 默认 `auto`，自身不滚动却作为最近滚动祖先，令内部 sticky 退化为静态位移）。实测：滚动 900px 后头部 `top=64` 与导航下沿重合；移动端（头部两行 158px）不加 sticky。侧栏仪表盘 `top:76` 的 sticky 也随之真正生效。

### 9.3 顺带（移动端）

- 顶栏：≤720 `gap/nowrap`，新增 ≤480 隐藏「AI 规划行程」按钮（底部 Tab 已有同入口）→ 修复 390px 下「随行」竖排、按钮折行

### 9.4 验证（真机 localhost:5173 + 8090）

- `npm run build` ✓
- 桌面：`.map-card(182..613) → .plan-tools(613..793) → .itinerary-head(811) → .day-card(847)` 顺序正确
- 备选方案切换 → 3 条差异 + 备选预算渲染 ✓
- 端到端真实 AI 调整（「第二天少安排一个景点」）→ 摘要 + 本次改动 1 项 + 质检 52/100 + 大纲 13→12 站 ✓
- 行中时机默认不显示；「更多 → 调整行程」唤出并滚到 `top=76`（导航下沿 64 + 12）✓
- 全部工具模式：工具箱内已无「AI 调整行程 / 行程备选方案」✓
- `?flag=tripDetail.ia.v2=off`：主路径无 PlanTools，工具箱内两者回归 ✓
- 移动端 390：无横向溢出，输入框与按钮全宽堆叠，头部不吸附 ✓

### 9.5 遗留（已在 §10 修掉）

- ~~后端 plan B 文案是英文 + `$`~~ → §10.1
- ~~移动端地图高度打架露灰带~~ → §10.2

---

## 10. 遗留问题修复（2026-10-29 夜）

### 10.1 Plan B 文案语言与货币符号

三层问题，逐一修：

| 层 | 问题 | 修法 |
|---|---|---|
| 前端 | 从未发 `Accept-Language`，浏览器默认带的是**系统语言**（本机 `en-US`）→ 后端 i18n 按英文出文案 | `api/http.js` 请求拦截器显式写 `Accept-Language = i18n.global.locale.value`（跟随 App 语言，LangSwitcher 切换即时生效） |
| 后端服务 | `currency = "¥" if zh else "$"` 与模板自带的符号叠加 → **`¥¥1080` / `$$1080`**（单测只断言子串 `"¥400" in d`，双双漏过） | 服务只传**裸数字**，货币符号由文案模板承载 |
| 后端币种口径 | 英文界面显示 `$`，但平台记账币种是 CNY（`budget.currency=CNY`），金额被换错符号 | 英文模板也统一 `¥`（不做汇率换算，只改符号） |

顺带：`estimated_cost` 为 0/null 的住宿不再参与预算档对比（否则出现「约 ¥0 → ¥0」的无信息量差异行）。

验证：`generate_plan_b_variant` zh/en 均输出 `约 ¥1080 → ¥756`、`约节省 ¥324`；API 按 `Accept-Language` 返回对应语种；真机中文界面显示「预算优化版 / 备选预算约 ¥1136 / 住宿 ¥756」。

### 10.2 移动端地图高度

**根因**：`TripMap` 内联 `height: 360px` + CSS 媒体查询 `height: 300px !important` 打架——元素最终 300px，但 Leaflet 在 `onMounted` 时按 360px 量容器，瓦片/画布按 360 排布，底部 60px 被裁出灰带，`fitBounds` 也偏。

**修法**：高度改为 JS 单一事实来源
- `heightPx = isNarrow ? min(prop, 300) : prop`（≤640px 视口压到 300）
- `matchMedia('(max-width: 640px)')` 监听断点变化 → `heightPx` 变化后 `nextTick()` + `map.invalidateSize()`
- 删掉 `!important` 媒体查询，避免再出现「CSS 与 Leaflet 各算一套」

验证：移动端 `.trip-map` 高 300px、瓦片铺满无灰带、无横向溢出；桌面仍 360px；`matchMedia` 监听在卸载时移除。

### 10.3 回归

- `npm run build` ✓
- `pytest tests/test_plan_b.py tests/test_plan_b_api.py tests/test_i18n.py` → 32 passed
- 全量 `pytest tests/` → **693 passed**（100.95s）
- 真机：中文 Plan B 文案 + ¥ 单符号、移动端地图铺满、桌面地图 360px 不变

