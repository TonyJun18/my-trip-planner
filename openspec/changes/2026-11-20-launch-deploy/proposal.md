# Proposal

## Why

项目（2026-11-14 数据库核对）从未上线 to-C：30 个测试用户 / 6 次全 self-test 规划 / 6 个 share_token / 0 条 gallery / 0 条 rating / `analytics_event` 表不存在；GitHub 0 stars / 0 forks。工程能力已被 1139 测试自证，**产品价值从未被外部验证**。2026-11-14 决裁（`docs/plans/2026-11-15-core-value-launch.md`）：to-C 上线验证主线，香港轻量免备案 + 空库 + 最小埋点 5 事件 + 14 天判定线（20 访问 / 5 完成 / 2 分享）。

现状核验（2026-11-20）：`backend/app/api/v1/analytics.py` 是「前端意图埋点」——**只写结构化日志、不落库**（`_EVENT_LABELS` 6 个意图事件：planning_tool_open/top_action_click/itinerary_first_view/itinerary_scroll_depth/workspace_tab_switch/workspace_all_toggle，返回 204）。本 change 要补的是**上线判定线所需的最小漏斗埋点**（page_view/register/plan_submitted/plan_completed/share_created），与既有意图埋点区分（判定线用新库表，不污染行程事件流）。

## What Changes

### 上线部署（W1）

- 香港轻量 2C2G + 域名 A 记录 + HTTPS 证书（宝塔反代/docker-compose 直接搬）。
- **全新空库初始化**，dev 测试数据绝不带上去（30 用户/6 self-test 残留）。
- 生产安全最小项：固定 `JWT_SECRET`、收紧 `CORS_ORIGINS`、关 debug、不暴露 5432。

### 最小漏斗埋点（5 事件）

- 新表 `analytics_events`（Alembic 迁移）+ `POST /analytics/event`（落库版）。
- 5 事件：`page_view` / `register` / `plan_submitted` / `plan_completed` / `share_created`。
- 前端打点：路由切换 page_view、注册成功 register、提交规划 plan_submitted、完成规划 plan_completed、创建分享 share_created。
- **与既有意图埋点区分**：新增 `dedicated` 落库端点（`POST /analytics/event` 现为 204 日志，改造为可落库或新增 `/analytics/funnel` 端点，见 Design D1）。
- 判定线脚本：`docs/nightly/` 数据聚合（访问→注册→提交→完成→分享 逐层转化率）。

### 运营（W2-W4）

- 朋友内测 5 人（未来 4-8 周有真实出行计划，含 ≥1 非技术用户）。
- 小红书 2-3 篇真实种草（诚实基调，不放外链）。
- 3-5 人种子访谈。
- W4 判定：达 20/5/2 → 解锁 §2 候选池；未达 → 止损（停服务器/回退作品集定位/内容资产）。

## Capabilities

### New Capabilities

- `launch-deploy`: to-C 上线验证主线——香港轻量部署、空库初始化、生产安全最小项、最小漏斗埋点 5 事件、14 天判定线取数。

### Modified Capabilities

- `analytics`: 既有意图埋点（`analytics.py` 日志版）保持；新增落库漏斗端点（判定线用）。

## Impact

- **部署**：香港轻量 + 域名 + HTTPS + 空库 + docker-compose。
- **后端**：`models/analytics.py`（analytics_events 表）+ Alembic 迁移 + `api/v1/analytics.py`（落库端点）+ 判定线脚本。
- **前端**：路由/注册/提交/完成/分享打点（`api/modules/analytics.js` 或复用）。
- **零破坏**：既有意图埋点不动；新端点独立；`trip_events` 不污染。
- **依赖**：服务器 + 域名（预算 ≤¥200，与止损线绑定）。