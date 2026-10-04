# 商店上架物料清单（Store Listing）· 随行 AI 旅行规划

> 状态：📋 **物料准备中**（本文件为审核与上架动作的清单；**不实际提交任何商店**，上架动作由用户手动执行）
> 目标平台：App Store（iOS）/ Google Play（Android）。A 阶段为 PWA，B 阶段为 Capacitor 壳（见 `docs/night-build-todo.md` 阶段 B）。
> 生成日期：2026-10-05

## 0. 产品一句话

> AI 旅行规划：可执行、可修订、可分享，弱网也能查看离线行程。

---

## 1. 商店元信息（App Store / Google Play 通用字段）

| 字段 | 值（中文） | 值（English） | 备注 |
|---|---|---|---|
| 应用名称（App Name） | 随行 · AI 旅行规划 | TripMate AI Trip Planner | Android 建议 <30 字符 |
| 副标题（Subtitle，iOS） | 行程规划 · 修订 · 分享 | Plan · Revise · Share | iOS 30 字符内 |
| 类别（Category） | 旅游（Travel） | Travel | 主分类：Travel；次分类：Lifestyle |
| 价格模型 | 免费（Free） | Free | 上线期免费，无内购计划 |
| 内容分级 | 4+（全年龄） | Everyone | 无暴力/成人/赌博内容 |
| 目标地区 | 中国大陆 + 海外中文用户 | Global | 需遵守各地区隐私与 AI 监管要求 |
| 隐私政策 URL | `https://<公网域名>/privacy` | 同左 | **已就绪**：`frontend/public/privacy.html`，nginx `/privacy` 路由已配 |
| 支持邮箱 | pengtony9@gmail.com | 同左 | 已写入 privacy.html |

### 关键词（iOS 100 字符 / Google 多关键词）
`AI 行程规划, 旅行计划, 攻略, 自由行, 行程修订, 离线行程, 自驾路线, 预算, 旅游笔记导入, 多人协作`

---

## 2. 图标（Icon）— ⚠️ 待补

| 规格 | 要求 | 现状 |
|---|---|---|
| App Store 图标 | 1024×1024 PNG，无透明通道，无圆角（系统裁切） | ❌ 待生成 |
| Google Play 图标 | 512×512 PNG，32 位（含 alpha），无圆角边框 | ❌ 待生成 |
| 自适应图标（Android） | 前景 512×512（safe zone 66%）、背景色 #ff385c | ❌ 待生成 |

**制作建议**：以现有品牌视觉为基础——品牌色 `#ff385c`、logo 为「📍 定位点 + 白色圆圈」图形（见 `frontend/index.html` favicon 与 `App.vue` brand-logo SVG，同源图形）。用 Figma/Icon Composer/sketch 出稿；不要用照片、不要用文字过多的小字。
**依赖**：本清单对应 PWA manifest icons（192/512 PNG）需求已登记在 `task-mobile-install`，生成 PNG 后此处同步复用。

---

## 3. 商店截图（Screenshots）— ⚠️ 待补

### 3.1 App Store（iPhone 6.7" + 6.5" 各 3-5 张，1290×2796 / 1242×2688）
| 序 | 画面 | 截图内容要点 | 配套文案（en） |
|---|---|---|---|
| 1 | 首页 / 行程列表 | 移动端行程卡列表（离线标识、预算、日期） | Plan trips in seconds |
| 2 | 规划向导 | 目的地 + 日期 + 偏好 → AI 生成行程骨架 | AI builds your itinerary |
| 3 | 行程详情（Day 视图） | 每日站点时间线 + 地图 + 预算 | Clear day-by-day plans |
| 4 | AI 修订 diff | 「让 AI 调整行程」前后对比 diff 预览 | Revise with AI, see every change |
| 5 | 分享协作 | 分享链接 + 评论/投票/受邀编辑 | Share & co-plan with friends |

### 3.2 Google Play（手机 2-8 张，16:9 或 9:16，推荐 1080×1920）
| 序 | 画面 | 要点 | 文案 |
|---|---|---|---|
| 1 | 行程列表 | 同 iOS-1 | Plan trips in seconds |
| 2 | 规划向导 | 同 iOS-2 | AI builds your itinerary |
| 3 | 详情 + 地图 | 同 iOS-3 | Day-by-day + map |
| 4 | 离线模式 | DevTools offline 下列表仍显示 + 离线徽标 | Works offline |
| 5 | 导入 | 粘贴笔记/邮件/链接/截图 → 站点候选 | Import your notes |

> 截图必须为**真实产品运行画面**，不允许合成 mockup 冒充；预留待 `task-capacitor-shell` 完成 web build 后取真机/模拟器截图。

---

## 4. 商店描述文案（可直接复制使用）

### 4.1 中文（应用商店版）

**随行 · AI 旅行规划——让 AI 帮你把想法变成可执行的行程**

出门前最头疼的事：攻略看了一堆,行程还是乱。随行帮你从「想法」到「可执行行程」一路打通。

**核心功能**
- 🧭 **AI 规划**：输入目的地、日期和偏好，多个 Agent 并行产出每日行程、预算与备选方案
- ✏️ **AI 修订**：任何不满意的地方说一句话，「让 AI 调整」——每次修订都有 diff 预览，改错可回退
- 📍 **地图拖拽**：拖动 marker 直接改站点，自驾超距自动拦截提示
- 👥 **分享协作**：一个链接进群，全员查看、评论、投票、受邀编辑，行程共识一键达成
- 💰 **诚实预算**：交通/住宿/餐饮/门票逐项估算，口径透明可修订
- 📥 **输入自由**：粘贴攻略笔记、预订确认邮件、分享链接，或上传截图，自动提取站点候选
- 📴 **离线可用**：行程数据本地缓存，弱网/无网也能查看，恢复在线自动同步
- 🌍 **中英双语**：界面一键切换

**适合谁**：自由行爱好者、多人结伴出行、自驾游小队、懒得做攻略又抵制「预订绑架」的旅行者。

**关于 AI 内容**：行程与预算由 AI 生成，仅供参考；出行前请以官方渠道核实班次、票价与营业信息。详见隐私政策。

### 4.2 English（App Store / Google Play）

**TripMate — AI trip planning you can execute, revise, and share**

Stop juggling ten tabs of guides. TripMate turns your ideas into an executable itinerary.

**Features**
- 🧭 **AI planning**: destination + dates + preferences → multi-agent itinerary with budget & plan B
- ✏️ **AI revision**: ask to adjust anything; every change shows a diff preview, reversible
- 📍 **Map drag-edit**: drag markers to fine-tune stops; driving-distance guardrails warn you early
- 👥 **Collaboration**: one link to share, comment, vote, and co-edit with your group
- 💰 **Honest budget**: itemized estimates with transparent assumptions, fully revisable
- 📥 **Import anything**: paste notes, booking emails, links, or upload screenshots → structured stop candidates
- 📴 **Offline first**: cached itineraries work on the subway, sync when you're back online
- 🌍 **Bilingual**: 中文 / English

**For** travelers who want planning freedom without being funneled into booking.

**AI disclaimer**: itineraries & budgets are AI-generated for reference only. Verify schedules, prices, and opening hours via official channels before you go.

---

## 5. 商店 FAQ（审核常见问题 → 应答）

| # | 审核问题 | 应答要点 |
|---|---|---|
| 1 | 应用是否需要登录？ | 需要（邮箱/手机号或 Google 登录），行程属于个人数据，匿名不可用 |
| 2 | 是否收集儿童数据？ | 不面向 14 岁以下，不故意收集；见隐私政策 §7 |
| 3 | AI 生成内容如何投诉/纠错？ | 产品内提供修订改错；隐私政策/支持邮箱可联系删除 |
| 4 | 是否出售用户数据？ | 否。仅按「必要且最小化」原则对接 AI/地图/搜索服务商 |
| 5 | 分享链接是否公开？ | 是，分享即公开，可随时删除链接/收回编辑权（产品内已实现） |
| 6 | 数据如何删除？ | 应用内可删行程；账号数据删除走支持邮箱（7 个工作日内） |
| 7 | 是否需要订阅/内购？ | 免费，无内购 |
| 8 | 是否支持离线？ | 已实现：行程缓存 + 离线标识（PWA） |

---

## 6. 上架待办与状态（诚实清单）

| 项 | 状态 | 负责 |
|---|---|---|
| /privacy 静态页（AI 免责 + 数据说明） | ✅ 已完成（本夜 `frontend/public/privacy.html` + nginx 路由） | 夜间 worker |
| 公网可访问域名 + HTTPS | ⏳ 待部署（现有 `deploy/README.md` Docker 包为内网/演示，公网需域名 + Caddy/Traefik） | 用户 |
| 图标 1024/512/自适应 | ⏳ 待生成（建议基于品牌 SVG 图形出稿） | 用户/设计 |
| 商店截图（5+5） | ⏳ 待 `task-capacitor-shell` 完成后真机截图 | 用户 |
| 应用内隐私链接（Landing 页 footer 增加 /privacy 链接） | ⏳ 可选优化（本轮未做，避免越界） | 后续 worker |
| Android 签名 keystore / Apple 开发者账号 | ⏳ 用户决定（涉及凭证，夜间不执行） | 用户 |
| 实际提交商店 | ⛔ **不使用凭证不提交**，上架动作由用户手动执行 | 用户 |

## 7. 关联任务
- `task-capacitor-shell`（todo[1]）：Capacitor 壳，APK 构建（本清单前置）
- `task-mobile-install`（todo[0]）：PWA 安装引导 + manifest PNG 图标（图标源素材与本清单 §2 共用）
- `task-pwa-cache-deep`（已完成）：离线能力是 §3.2 截图 4 的真实素材