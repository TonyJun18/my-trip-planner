# Proposal

## Why

行程详情页的每日日程只显示「N 站 · ¥587 · 17h30m」这类聚合数字——用户看不到每站几点出发、几点到达，段间交通耗时也不可见；一天 17.5 小时的过载行程毫无视觉感知（真机体验实证，上海行程 D2）。排程时间轴是行程类产品的结构级缺口（Wanderlog / Mindtrip / Stippl 均为标配），且 TimeGate 已有 cursor 推时刻的确定性能力，只差把结果渲染出来。

## What Changes

- 新增纯函数排程器 `schedule_service.schedule_day`：按「日起点 9:00（与 TimeGate 同源常量）+ 逐站游玩时长 + 相邻站点球面距离估时」确定性推算每天每站的起止时刻与段间交通耗时，住宿站不占游玩时段（渲染为「入住」），超出一天的跨夜钳制并返回过载信号。
- 读取路径（`GET /trips/{id}` owner 详情、分享 token 只读、行中 `GET /trips/{id}/live` 快照）在响应层注入派生字段 `visit_start / visit_end / travel_to_next_minutes / is_transfer`；Stop 表零 DDL、全部写路径零挂钩——时刻是派生值，与「预算由代码重算」哲学同构，永远不脏。
- multi_city 交通占位站的 `is_transfer` 标记随落库持久化到 `details`（存量行程按名称「（交通占位）」后缀兼容识别）。
- 前端 `TripDetailDayCard` 升级为时刻流水线：站点行时刻徽标（🏨 入住、🚄 交通样式）、段间交通 chip、日头时间窗口（`08:30 → 21:00`，替代裸时长）与跨夜/超 12h 过载红色高亮；`TripDetailLiveToday` 行中今日卡同步展示时刻。
- 轻量顺带：行程问答卡（`TripDetailQaCard`）接口错误态与「暂无结构化数据」空态分离，错误态给「数据加载失败 + 重试」。

## Capabilities

### New Capabilities

- `trip-schedule-timeline`: 行程每日站点的确定性排程时间轴——读取路径派生起止时刻/段间交通/占位站识别/过载信号，三个消费端（owner 详情、免登录分享、行中快照）的响应契约与前端渲染要求。

### Modified Capabilities

<!-- 无既有 capability 的需求级变更（现有 specs 仅 favorite-spots，与之无关） -->

## Impact

- **后端**：新建 `backend/app/services/schedule_service.py`；`backend/app/schemas/trip.py`（StopOut 派生字段）；`backend/app/api/v1/trips_crud.py` get_trip、`trips_share.py` 分享读路径、`live_service.py` 快照注入；`planning_service._persist_trip` details 白名单补 `is_transfer`（两行）。
- **前端**：`TripDetailDayCard.vue`、`TripDetailLiveToday.vue`、`TripDetailQaCard.vue`；i18n zh/en 约 6-8 键。
- **零破坏**：无 DDL、无写路径变更、无 API 请求契约变更（仅响应新增可选字段）；既有 453 测试应零回归。
- **依赖**：仅复用既有 `time_validation.DAY_START` 与 `driving_service.estimate_drive_minutes`，无新依赖。
