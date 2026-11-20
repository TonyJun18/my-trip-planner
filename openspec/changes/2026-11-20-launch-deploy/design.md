# Design

## Context

- 既有资产：`docs/plans/2026-11-15-core-value-launch.md`（12 条决策 + 4 周计划）、docker-compose 部署栈（PG17 内 5432 / 外 5433、前端 8080 nginx 反代 `/api` `/ws`）、`backend/app/api/v1/analytics.py`（前端意图埋点，日志版 204）、`e2e-verification` 验收套路（固定 JWT_SECRET + 重新登录）。
- 核验（2026-11-20）：`analytics.py` 只写日志不落库（`_EVENT_LABELS` 6 事件）；`analytics_events` 表不存在。
- 约束：预算 ≤¥200（服务器 ¥40/月 × 3 + 域名 ¥70，与止损线绑定）；免备案；空库；判定线 20/5/2。

## Goals / Non-Goals

- **Goals**：上线可达 + 空库 + 生产安全最小项 + 5 漏斗事件落库 + 判定线取数 + 运营闭环。
- **Non-Goals**：备案；付费经济；拉量投放；复杂 BI；意图埋点落库改造。

## Decisions

### D1. 新增独立 `analytics_events` 表 + `dedicated` 标志复用端点 vs 新端点
复用既有 `POST /analytics/event` 加 `dedicated: bool = false` 标志（`true` 走漏斗白名单落库），
避免新增路由面；`false`/缺省保持日志 204。备选「新端点 /analytics/funnel」被否：同表结构、
同请求面，一个标志更收敛。白名单 5 事件 + 匿名 session 关联（不强制登录）。

### D2. `analytics_events` 与 `trip_events` 彻底分离
判定线数据是「产品漏斗事实」，行程事件流是「行程内协作事实」——同一张表会互相污染口径
（launch plan 铁律：不挂 trip_events）。独立表 + 独立迁移；`page_view` 不要求登录（捕获全漏斗，
匿名用 `anonymous_session_id`（前端生成 UUID，localStorage 持久）关联同一访客多次访问）。

### D3. 前端打点 fire-and-forget + 失败静默
与既有意图埋点同构：`api/modules/analytics.js` 封装，`silent: true`（不弹全局 toast），
失败不影响业务。五处打点对应既有事件触发点（路由 afterEach / 注册成功回调 / PlanWizard 提交 /
完成回调 / ShareView 创建分享）。

### D4. 判定线脚本独立，不嵌业务
`backend/scripts/launch_judgment.py` 只读聚合（直接查 analytics_events），输出逐层转化率 + 达标布尔；
不新增 API 端点（脚本仅供运营自用，避免暴露产品数据面）。第 14 天结算结果写 `docs/nightly/`。