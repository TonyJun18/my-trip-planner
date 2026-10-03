# PRD: 移动端路线 A→B（PWA 深度升级 → Capacitor 上架）

**Status**: Approved（2026-10-03 用户确认"先做 A，然后做 B"）
**Author**: Alex (PM)  **Last Updated**: 2026-10-03  **Version**: 1.0
**Stakeholders**: 彭军（唯一开发者/owner）、夜间流水线 night-worker

---

## 1. Problem Statement（问题陈述）

产品已经是一款可安装、可离线的 PWA（Service Worker + manifest + 离线详情已入 main），但**移动端体验停留在"桌面 Web 缩小版"**：

- 顶栏导航在 375px 视口拥挤（品牌 + 3 个导航 + 语言切换 + 用户头像），无底部 Tab，单手持机不可达
- 三大核心视图（PlanWizard 1127 行 / TripDetailView 1338 行 / ShareView 599 行）未做断点布局，表格与横向卡片在窄屏排版劣化
- PWA 壳有"可安装"能力但无"引导安装"行为：没有 `beforeinstallprompt` 处理、没有 iOS apple-touch-icon / apple-mobile-web-app meta、manifest 只有 SVG 图标（Chrome 安装要求 192/512 PNG）
- 离线能力只覆盖行程详情单页，列表与分享页断网即白屏

不解决的代价：移动端是 AI 旅行规划的真实使用场景（旅行中查看/修订），体验劣化直接削弱"免费/透明/可修订/可协作/可自托管"的规划层定位，也让作品集展示（OPC 已确认的 C-资产沉淀主线）少一块"移动端可安装"的说服力。

**Evidence:**
- 代码现状：App.vue 仅有一段 `@media (max-width: 720px)` 微调；9 个视图无系统性移动适配
- manifest.webmanifest：仅 `icon.svg`（sizes=any），无 192/512 PNG；无 `apple-touch-icon`
- PWA 基座已在（2026-10-03 task-pwa-offline 入 main），深化成本低
- 竞品信号：AiGo 以 PWA 离线为核心卖点，无一家把原生 App 当核心——移动端是标配，原生不是

## 2. Goals & Success Metrics（目标与成功指标）

| Goal | Metric | Current Baseline | Target | Window |
|------|--------|-----------------|--------|--------|
| 移动端主流程可用 | 375px 视口下 规划/详情/分享编辑 三流程可用（人工验收清单） | 部分可用（排版劣化） | 全流程可用、无水平滚动 | 每任务验收 |
| 可安装性 | Chrome 安装引导出现 + Safari 可添加到主屏幕 | 无引导、Safari 差（无 meta/icon） | 双端可安装 | task-mobile-install |
| 离线可用面 | 断网可查看 列表+详情+分享页 | 仅详情（API 缓存） | 列表+详情+分享 | task-pwa-cache-deep |
| PWA 体检 | Lighthouse PWA 分数 | 未测（基线低） | ≥ 90 | 全部 A 任务完成后 |
| B 阶段打包 | npx cap sync android 通过 + 构建产物可安装 | 无 Capacitor | 可装模拟器/真机 | task-capacitor-shell |

> 注：无埋点/无真实用户，安装率/漏斗类指标无法度量。以可验证的工程指标为准，不编造产品指标。

## 3. Non-Goals（不做的事）

- **不做原生重写（方案 C 否决）**：Flutter/RN 双前端单人维护成本过高，与资产沉淀主线冲突。记入"我们不做什么"：若未来出现真实用户规模再评估。
- **B 阶段不实际提交上架**：无商店账号（iOS $99/年 + Android $25）+ 审核流程未知。壳与物料先行，上架动作由用户确认后单独执行。
- **不做 iOS 推送 / Android 推送**：需原生能力 + 后端推送服务，超出本轮。
- **不做多币种 / 新后端功能**：纯前端移动化 + 打包路线，后端 API 零改动（除 /privacy 静态页）。
- **不做离线编辑**：离线仅只读（与现有离线详情语义一致）。

## 4. User Personas & Stories（用户画像与故事）

**Primary Persona**: 旅行中的用户——手机上快速查看今天的行程、点开分享链接参与同伴投票、弱网/断网时仍能看行程。

**Story 1**: 作为旅行中的用户，我想要用底部 Tab 在"我的行程 / 新建规划"间切换，以便单手操作。
**Acceptance Criteria**:
- [ ] 登录态 375px 视口显示底部 Tab（我的行程 / 规划），未登录态不显示
- [ ] 顶栏在窄屏压缩为品牌 + 语言 + 用户入口，不换行、不溢出
- [ ] footer 在移动端隐藏
- [ ] 无水平滚动（375px 视口横向 scrollWidth ≤ 375）

**Story 2**: 作为弱网用户，我想要断网时仍能查看行程列表与分享页，以便在无信号区域（地铁/山区）不白屏。
**Acceptance Criteria**:
- [ ] 断网（DevTools offline 模拟）打开 /trips 显示缓存列表 + 离线标识
- [ ] 断网打开已缓存行程的分享页可读内容
- [ ] 恢复在线自动清除离线标识并刷新

**Story 3**: 作为 Chrome/Safari 用户，我想要被引导安装本应用到主屏幕，以便像 App 一样全屏启动。
**Acceptance Criteria**:
- [ ] Chrome 触发 beforeinstallprompt 时显示可关闭的安装提示（非侵入式，仅登录用户）
- [ ] Safari 可"添加到主屏幕"，全屏启动（apple-mobile-web-app-capable）
- [ ] manifest 含 192/512 PNG 图标，安装后图标正常

**Story 4（B 阶段）**: 作为用户，我想要从应用商店安装 Android 版本。
**Acceptance Criteria**:
- [ ] Capacitor 壳构建通过，Android 工程可 sync、打包 APK
- [ ] API 地址可通过配置注入（非硬编码）
- [ ] /privacy 公开路由可访问（商店审核必备）

## 5. Solution Overview（方案概述）

分两阶段：
- **阶段 A（4 任务，纯前端）**：移动 App Shell（底部 Tab + 顶栏压缩 + footer 移动隐藏）→ 三大视图断点适配 → PWA 安装引导（beforeinstallprompt + iOS meta + PNG 图标）→ 离线深化（列表/分享页缓存 + SW 更新提示）。全部复用现有 Vue3 代码，后端零改动。
- **阶段 B（2 任务，用户确认后执行）**：Capacitor 壳（Android 优先，iOS 需 Apple 开发者环境，不可用则记 issues 降级验证 web build）→ 上架物料（/privacy 页 + 商店文案/截图清单文档）。不实际提交审核。

**关键设计决策:**
- 底部 Tab 只放 2 个主入口（行程/规划），详情、分享保持路由跳转——避免 Tab 数量膨胀
- 安装提示只在登录用户 + 未安装 + 本地存储标记未关闭时出现——非侵入式
- 离线列表缓存采用"列表静默缓存 + 详情按需缓存"策略，延续现有 network-first 语义
- B 阶段用 Capacitor 而非 cordova/Tauri：同一 JS 代码、生态成熟、与 Vite 构建产物对接最顺

## 6. Technical Considerations（技术考量）

**Dependencies**:
- @capacitor/core + @capacitor/cli + @capacitor/android（B 阶段新增 npm 依赖）— owner: 彭军 — risk: Low（官方维护）
- Apple 开发者环境（iOS 打包）— owner: 外部 — risk: High（无账号则跳 ios 平台，只做 android）

**Known Risks**:
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| 移动断点适配破坏桌面布局 | Medium | Medium | 每任务验收含 1280px 视口回归；严格断点隔离 |
| SW 策略加深引入缓存污染 | Low | Medium | 延续白名单 + network-first；写请求一律不拦截 |
| Capacitor 构建需要 Android SDK/Java 环境 | Medium | High | 环境不可用 → 记 issues 降级验证（web build + cap sync 到 android 目录生成），不伪造 APK |
| iOS 商店审核对 AI 内容的要求 | Low | High | /privacy 明确 AI 生成内容免责与人工修订能力；物料文档记录 FAQ 口径 |

**Open Questions**:
- [ ] 上架名称与包名（建议 com.tonyjun.tripplanner，待确认）— Owner: 彭军 — Deadline: B 阶段启动时
- [ ] Android SDK 本机是否可用 — Owner: 彭军 — Deadline: task-capacitor-shell 执行时检测

## 7. Launch Plan（发布计划）

| Phase | Date | 内容 | Success Gate |
|-------|------|------|--------------|
| A1 mobile-shell | 夜间流水线 | App Shell 移动化 | build 通过 + 375px 导航可用 |
| A2 mobile-views | 夜间流水线 | 三视图断点适配 | build 通过 + 三流程可用 |
| A3 mobile-install | 夜间流水线 | 安装引导 | build 通过 + 双端可安装 |
| A4 pwa-cache-deep | 夜间流水线 | 离线深化 | build 通过 + 断网三页可用 |
| B1 capacitor-shell | 夜间流水线（A 完成后） | Android 壳 | cap sync 通过 + 产物可装（或降级验证） |
| B2 capacitor-stores | 夜间流水线 | 物料 + /privacy | /privacy 可访问 + 物料文档存在 |
| 上架提交 | 用户手动 | 商店审核 | 用户确认后执行，不入流水线 |

**Rollback Criteria**: 任何任务破坏桌面端现有体验（build 失败 / 1280px 回归）→ 该任务分支不合并，回退仅涉及新增 CSS/依赖，无数据库变更。

## 8. Appendix（附录）

- 任务源：docs/night-build-todo.md「2026-10-03 用户白天下达任务（移动端 A→B 路线）」小节
- 现有 PWA 基座：frontend/public/sw.js、manifest.webmanifest、TripDetailView 离线降级
- 相关文章：docs/articles/05-map-edit-paradigms.md（移动端交互范式）; docs/articles/07-open-planning-layer.md（自托管定位）