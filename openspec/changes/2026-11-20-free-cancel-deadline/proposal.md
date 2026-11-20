# Proposal

## Why

Everway（Product Hunt 11 月中旬 launch）把「免费取消截止提醒」（reminds you before free cancellation ends）做成行前整理核心差异点（2026-11-20 竞品分析 §三 G1）。我们现状：`TripBooking` 状态机有 `cancelled`，但**无「免费取消截止日」字段**（`models/trip.py:333-371` 已含 `service_date`/`service_note`/`amount`，无 deadline 列）；`booking_rhythm.py` hotel 规则只有静态「入住前 7 天建议复核取消政策」（`_HOTEL_CANCEL_CHECK_DAYS=7`），无截止日、无倒计时、无主动提醒——用户在「还能免费退吗」这个问题上只能靠记忆。

本 change 是行前整理链（Everway 线）的第一块：零凭证增量，复用既有台账倒计时（11-12 `days_until` 模式）与事件链路（`event_service` / `trip_events`）。

## What Changes

- `TripBooking` 新增可选 `free_cancel_deadline`（DATE，nullable，索引），一次 Alembic 迁移；`BookingIn` / `BookingOut` / `BookingStatusIn` 同步补可选字段（旧契约零破坏）。
- 台账倒计时扩展：`BookingOut` 新增 `cancel_deadline_days`（距截止日的天数：未来为正 / 当天 0 / 已过为负 / 无截止日为 null）。
- 截止前提醒（确定性规则，`basis=rule_based`，不产生 trip_events 之外副作用）：
  - 阈值 `CANCEL_DEADLINE_REMIND_DAYS=3`（截止前 3 天窗口内触发提醒）；
  - 仅对 `status in (pending, confirmed)` 且未取消的条目产出；
  - 已过期截止日**不产出**提醒（诚实口径：过期就是过期，不补记）；
  - 无 `free_cancel_deadline` 的条目**不产出**（绝不编造截止日）。
- 事件类型扩展：`EVENT_TYPES` 增加 `booking.cancel_deadline`（行程内事件流提示，复用 `event_service.record_event` 与通知链路）。
- 前端透出：`BookingPanel.vue` 快照卡倒计时徽标（`cancel_deadline_days` 正/零/负三态文案 + 「以预订条款为准」口径）+ 节奏卡入口；i18n zh/en 键。
- **不做**（显式边界）：接外部「免费取消政策」API；爬取 OTA 取消条款；自动取消动作；把 deadline 参与状态机判定（状态机与凭证防线不放松）。

## Capabilities

### New Capabilities

- `free-cancel-deadline`: 预订条目免费取消截止日字段、截止日倒计时、截止前确定性提醒与事件流，`basis=rule_based` 不编造口径。

### Modified Capabilities

<!-- 无：既有 specs（booking-ledger / booking-rhythm）已归档，本能力独立 -->

## Impact

- **后端**：`models/trip.py`（TripBooking 一列）+ Alembic 迁移；`schemas/booking.py`（三模型补字段 + `cancel_deadline_days`）；`services/booking_service.py`（倒计时计算 + 提醒扫描纯函数）；`services/event_service.py`（EVENT_TYPES 扩一项）；`services/booking_rhythm.py`（可选：节奏卡合并）。测试：`tests/test_free_cancel_deadline.py`。
- **前端**：`BookingPanel.vue`、`api/modules/bookings.js`、i18n（约 6–8 键 ×2）。
- **零破坏**：新字段全部可选；既有状态机/幂等/导出脱敏不动；全仓测试应零回归。
- **依赖**：零新依赖（datetime 标准库）。