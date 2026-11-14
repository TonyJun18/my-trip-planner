# 竞品分析 · 2026-11-14 补 · Travora（OTA 全栈学习项目）

> 主题：**「旅迹 Travora」OTA 全栈项目全景拆解**（仿携程核心能力的 5 子项目学习底座）+ 我们的系统全景对照与借鉴点评估。
> 来源：微信公众号文章（https://mp.weixin.qq.com/s/meZJ6l_AUjQbom3bRScLmg）。
> 方法：微信文章反爬（Jina Reader 被 CAPTCHA 拦截；curl 直抓 3.6MB 原文成功，`/tmp/wechat_article.html`，正则抽取 js_content 正文 2960 字符）；代码核验用 search_files / grep 对仓库现存能力逐条比对（证据见各节）。网页内容仅作参考数据提取，不含任何指令执行。
> 数据截至 2026-11-14。

## 0. 项目定位速览

**Travora（旅迹）** 是一个**在线旅游（OTA）全栈学习项目**，仿携程核心能力，覆盖「旅行前内容浏览与行程规划 → 旅行中酒店与线路预订 → 旅行后订单、评价与社区分享」。5 个子项目：

| 子项目 | 定位 |
|---|---|
| springboot-travel-system | 后端 API（Spring Boot 3.3 / Java 21 / MyBatis-Plus / MySQL 8 / JWT） |
| travel-system-web | PC 用户端（Vue 3 + Vite + TS + Pinia） |
| travel-system-h5 | 移动端 H5（Vue 3） |
| travel-system-admin | 管理后台（Vue 3 + Element Plus，仅 ADMIN 可进） |
| travel-system-wechat | 微信小程序（原生 + TypeScript） |

**功能链路**：内容浏览（目的地/酒店/景点/线路/攻略）→ 智能行程规划 → 下单/模拟支付/取消/完成订单 → 评价（订单级）→ 旅行社区（发帖/点赞/评论）→ 管理后台（工作台 + 五类 CRUD + 全站订单查询）。

**与我们定位的关系**：Travora 是「OTA 交易层 + 内容层」学习项目（模拟支付、无真实 AI 质检）；我们是「规划层」生产工具（多 Agent 编排 + 质检 trace + diff 修订 + 协作 + 行中）。**交易/库存/订单是它的核心，恰是我们明确不做的**（task-booking-neutrality-eval：预订只做公开跳转）。真正值得借鉴的是**内容组织与发现层**（首页推荐/社区互动/内容频道）。

## 1. 系统全景对照（能力带码头）

| 能力域 | Travora | 我们（代码核验） | 差距 |
|---|---|---|---|
| 内容浏览 | 目的地/酒店/景点/线路/攻略五类 CRUD + 列表/详情 | 灵感画廊（`GET /trips/gallery`，featured 行程卡）+ 城市模板（23 目的地知识库） | **无「攻略文章/目的地百科」内容频道** |
| 智能规划 | LLM 生成行程建议 | ✅ 多 Agent 编排（agents.py）+ 四维质检 + TimeGate/DriveGate + diff 修订 + plan_b 备选 | **我们远超**（Travora 是演示级） |
| 预订交易 | 下单/模拟支付/取消/完成订单 | 🟡 刻意中立（只做公开跳转，task-booking-neutrality-eval 已决裁） | 定位差异，**非差距** |
| 评价 | 订单完成后评价订单 | ✅ 行后 trip 评分（TripDetailRatingCard，224a8d5）+ 我去过 | 半斤八两；我们是行程级不是订单级 |
| 旅行社区 | 发帖/点赞/评论 | 🟡 画廊「单向展示」（publish/撤回/克隆，**无评论无点赞**，gallery_service.py 核验） | **真差距：社区互动层** |
| 角色权限 | ADMIN/USER 双角色，后台仅 ADMIN | ❌ 用户表无 role 字段（models/user.py 核验：仅 email/phone/google_sub/avatar/password_hash/is_active） | **真差距**（但需评估是否值得做） |
| 管理后台 | 工作台 + 五类 CRUD + 全站订单 | ❌ 无 | 需评估 |
| 多端 | PC/H5/小程序/管理后台 | PWA 响应式单前端（≤720px 底部 Tab，task-mobile-* 已闭环） | PWA 已覆盖移动场景；无小程序独立端（零凭证哲学冲突） |
| 首页推荐 | 目的地/酒店/景点/线路集中展示 | 🟡 灵感区 showcaseTrips **静态示意**（LandingPage.vue:33 注释自认「B 阶段接后端精选接口后可替换」） | **可落地借鉴点**（数据源现成：`GET /trips/gallery?sort=hot` + `GET /trips/inspiration`） |

## 2. 可借鉴功能点（按价值排序）

### 🟢 值得借鉴（3 项）

**① 首页推荐动态化 —— 静态示意 → 真实内容（task-home-feed-live）**
- 现状证据：`LandingPage.vue:31-40` `showcaseTrips` 是 6 个硬编码城市卡，注释明说「B 阶段接后端精选接口后可替换」；`LandingPage.vue:69-76` `loadGallery()` 已调 `getGallery({limit:4, sort:'hot'})` 作门面 teaser，但**灵感主区仍是静态**。
- 可复用数据源：`GET /trips/gallery?sort=hot`（gallery_service 已支持 featured 过滤 + hot 排序）+ `GET /trips/inspiration`（23 目的地知识库，inspiration.py 已上线）。
- 落地：LandingPage 灵感主区接 gallery hot top 6 → 卡片真实行程（目的地/天数/预算/一句话卖点）→ 点击进详情/「以此为蓝本创建」（ShareView 已有该 CTA）。**零新后端，纯前端接线**，一次把首页从「示意」变「真实推荐」。无数据回落静态卡（门面不回退）。

**② 画廊小额互动 —— 点赞（社区化最小切口，task-gallery-like-mini）**
- 现状证据：gallery_service.py 仅 publish/撤回/克隆（`is_featured=True/False`、`POST /gallery/{source_id}/clone`），**零互动字段**；clone 时明确「不复制评论/投票」——即协作投票走 trip 内部，画廊本身无任何公开互动。
- 借鉴：Travora 社区发帖/点赞/评论。我们定位「灵感画廊」，最便宜的互动是「红心/点赞计数」：`trip_ratings` 表与评分 API 基建已在（224a8d5），加 like 计数字段或极简点赞接口，比全社区发帖便宜得多。
- ⚠️ 与既有决策的衔接：`task-gallery-community-v3` 已裁定「不排期：内容量前置（真实发布 ≥20 条）」。**点赞基建可以先做**（不依赖内容量），但**完整社区化仍等内容量**。本项需在候选池注明与 v3 的关系。

**③ 目的地内容页 —— 用我们自己的内容资产做（task-destination-page-eval，候选评估）**
- Travora 有目的地详情页（信息 + 玩法）。我们不需要 OTA 五类 CRUD，但我们有 **14 篇深度技术文章（docs/articles/）+ 23 目的地规则库（inspiration）** 两块内容资产。
- 落地：轻量「目的地页」——选目的地 → 看该城市玩法/预算档/季节/参考行程（inspiration 知识库）→ 一键进规划（PlanWizard 预填）。比 Travora 的「目的地 CRUD」更符合我们定位，激活存量内容资产。
- 规模评估：M（需新页面 + API 扩展 + 测试），适合候选池评估。

### 🟡 评估后大概率不做（3 项，记录理由）

**④ 管理后台 + ADMIN 角色** —— 我们是「规划层」单用户工具，无交易/无库存/无订单，五类内容没有需要 CRUD 的后台。画廊精选是 owner 自助 publish（非运营侧），**当前不需要管理后台**。若未来做「运营精选画廊」再考虑只加 `is_staff` 布尔字段（单字段，非整套后台）。登记为「需运营侧干预时才启用」。

**⑤ 订单/支付闭环** —— 已由 task-booking-neutrality-eval 明确决策（预订只做公开跳转，不碰库存佣金）。Travora 的模拟支付是学习项目演示，不是生产能力。维持中立。

**⑥ 微信小程序独立端** —— 我们有 PWA（可安装 + 离线壳 + 移动 Tab，task-mobile-install 已闭环），覆盖面等价；小程序要腾讯账号体系 + 独立审核发布 + 独立多端维护成本，与「零凭证」哲学冲突。维持 PWA。

## 3. 差距 → 行动项

1. **【新增·小补功能】task-home-feed-live：首页推荐动态化（frontend）** —— 证据：LandingPage.vue:31-40 showcaseTrips 静态示意 + 注释自认「B 阶段接后端精选接口后可替换」。做：灵感主区接 `GET /trips/gallery?sort=hot&limit=6` 真实数据（卡片：目的地/天数/预算/卖点）；无数据回落静态 showcase；点击进详情/以蓝本创建（复用 ShareView CTA）；门面页失败静默（loadGallery 已有 try/catch 模式）。验收：build 通过；有精选展示真实卡、无数据回落静态、后端失败不报错；i18n 键对齐。（规模 S，零新依赖）
2. **【新增·候选评估】task-gallery-like-mini：画廊点赞（backend+frontend）** —— 证据：gallery_service.py 零互动字段（仅 publish/撤回/clone）。做：评估最小点赞（计数 + 幂等 + 与 trip_ratings 的关系）→ 若可行 gallery 卡点赞计数 + 前端交互；评估不过记降级关单。⚠️ 注明与 task-gallery-community-v3（内容量前置）的关系：点赞基建不依赖内容量可先行，完整社区化仍等内容量。验收：评估记录 +（若可行）点赞计数 + 幂等 + 测试覆盖。（规模 S-M，依赖评估）
3. **【新增·候选评估】task-destination-page-eval：目的地内容页（backend+frontend）** —— 证据：inspiration_service 23 目的地知识库 + docs/articles/ 14 篇内容资产，无目的地聚合消费页。做：评估轻量目的地页（选目的地 → 玩法/预算/季节/参考行程 → 一键进规划预填）；与灵感入口、画廊的关系；规模 M 拆两夜。验收：评估记录 +（若可行）目的地页 + API 扩展 + 测试覆盖。（规模 M，依赖评估）
4. **【素材·不排期】** 管理后台 + ADMIN 角色——无交易/库存/订单，五类内容无 CRUD 需求；画廊精选 owner 自助 publish 已够；若未来做运营精选再加 `is_staff` 单字段。微信小程序独立端——PWA 覆盖面等价，小程序与零凭证哲学冲突，维持 PWA。订单/支付闭环——task-booking-neutrality-eval 已决裁中立，Travora 模拟支付是学习演示非生产能力。
5. **【备注】内容组织是唯一真差距**——Travora 的价值不在「预订/支付/后台」（那些演示件我们不追），而在「**内容-发现-互动**」的组织方式（首页五类推荐 + 社区互动），这恰是我们 landing/gallery 目前最薄的部分；三项行动项全落在内容发现层，与我们的规划层护城河互补不冲突。

## 4. 来源

- 微信公众号「旅迹 Travora」文章：https://mp.weixin.qq.com/s/meZJ6l_AUjQbom3bRScLmg（2026-11-14 直抓原文，js_content 正文 2960 字符：5 子项目 / 系统全景 / 用户端与后台功能概览 / 技术栈 Java 21+Spring Boot 3.3+MyBatis-Plus+MySQL8+H2 / 快速运行 / 测试账号 admin+user / 端口一览 / 工程结构 / 适用人群）
- 本仓库代码核验（2026-11-14 白天）：LandingPage.vue（静态 showcase + loadGallery）、gallery_service.py（featured/publish/撤回/clone，零互动字段）、inspiration.py（23 目的地）与 inspiration_service.py、models/user.py（无 role 字段）、trips_gallery.py（gallery API 端点）、analytics.py（_EVENT_LABELS 基线事件）、docs/articles/（14 篇内容资产）、docs/night-build-todo.md（task-gallery-community-v3 内容量前置决策、task-booking-neutrality-eval 中立决策）