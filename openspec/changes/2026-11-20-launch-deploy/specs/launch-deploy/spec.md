# launch-deploy Specification

## Purpose

把项目真正发布到 to-C 环境并建立最小验证闭环：香港轻量部署（空库、生产安全）、5 个漏斗埋点事件
落库、14 天判定线（20 访问 / 5 完成规划 / 2 分享）取数。上线本身就是最大杠杆——产品价值从未被外部验证。

## ADDED Requirements

### Requirement: 生产部署（香港轻量 + 空库 + 安全最小项）

系统 SHALL 部署到香港轻量服务器（2C2G，免备案）：域名 A 记录解析 + HTTPS 证书 + docker-compose
（后端 + PG + 前端 nginx 反代）就绪。生产库 SHALL 为全新空库（dev 测试数据绝不带入）。
生产安全 SHALL 满足四项最小项：`JWT_SECRET` 固定非空、`CORS_ORIGINS` 收紧为真实域名、`DEBUG` 关闭、
Postgres 端口不暴露公网（仅内网/容器内）。

#### Scenario: 上线可达

- **WHEN** 用户访问 `https://<域名>`
- **THEN** 返回前端页面（200），HTTPS 证书有效，无混合内容警告

#### Scenario: 空库初始化

- **WHEN** 检查生产库
- **THEN** 无 dev 测试数据（0 个测试用户 / 0 条 self-test 规划残留）

#### Scenario: 安全最小项

- **WHEN** 检查生产配置
- **THEN** JWT_SECRET 非空且非默认、CORS 仅真实域名、debug=false、5432 不暴露公网

### Requirement: 最小漏斗埋点 5 事件落库

系统 SHALL 提供落库版埋点：新表 `analytics_events`（Alembic 迁移）+ `POST /analytics/event`（或独立
漏斗端点）记录 5 类事件：`page_view`（访问）/ `register`（注册）/ `plan_submitted`（提交规划）/
`plan_completed`（完成规划）/ `share_created`（创建分享）。每条事件 SHALL 含：event_name、created_at、
（可选）user_id / trip_id / anonymous_session_id、payload（来源页/渠道）。

#### Scenario: 漏斗事件落库

- **WHEN** 访问者打开首页 → 注册 → 提交规划 → 完成规划 → 创建分享
- **THEN** analytics_events 表依次出现 5 条对应事件，各带时间戳与关联 id

#### Scenario: 匿名访问也记录

- **WHEN** 未登录访客打开首页
- **THEN** page_view 事件落库（anonymous_session_id 关联），不要求登录

### Requirement: 既有意图埋点零破坏

既有 `POST /analytics/event`（前端意图埋点，6 事件，日志版 204）SHALL 保持行为不变；新落库端点
（或 `dedicated: true` 标志）与既有区分，不混用。

#### Scenario: 意图埋点回归

- **WHEN** 前端发既有意图埋点（planning_tool_open 等）
- **THEN** 仍 204 日志（不落库），行为与现状完全一致

### Requirement: 14 天判定线取数

系统 SHALL 提供判定线数据脚本（`docs/nightly/` 或 backend/scripts）：从 analytics_events 聚合
访问→注册→提交→完成→分享 逐层转化率；14 天结算时对照判定线（20 真实陌生人访问 / 5 完成真实规划 /
2 分享或收藏）。不达线 SHALL 触发止损预案（停服务器 / 回退作品集定位 / 内容资产）。

#### Scenario: 判定线达标

- **WHEN** 14 天结算，库中真实陌生人访问 ≥20、完成规划 ≥5、分享/收藏 ≥2
- **THEN** 判定通过，解锁 §2 候选池，继续产品线

#### Scenario: 判定线未达

- **WHEN** 14 天结算未达 20/5/2
- **THEN** 执行止损：停服务器（或降配保留 demo）、回退作品集定位、把真实数据写成内容资产

