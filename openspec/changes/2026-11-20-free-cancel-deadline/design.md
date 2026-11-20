# Design

## Context

- 既有资产：`TripBooking` 状态机（suggested → pending → confirmed ⇄ cancelled，confirmed 必须带凭证，`models/trip.py:333-371`）、`service_date`/`service_note`/`days_until` 台账倒计时（11-12 booking-ledger）、`booking_rhythm.py` hotel 取消检查规则（`_HOTEL_CANCEL_CHECK_DAYS=7` 静态文案）、`event_service.EVENT_TYPES` 事件流（`booking.confirmed`/`booking.cancelled` 已有）。
- 缺口：无「免费取消截止日」字段、无倒计时、无截止前主动提醒。
- 约束（硬边界）：零凭证 / 零 LLM / 不编造（无截止日 = 无提醒）/ `basis=rule_based` 诚实标注 / 状态机与凭证防线不放松。

## Goals / Non-Goals

- **Goals**：截止日字段 + 倒计时透出 + 截止前 3 天确定性提醒 + 前端三态徽标。
- **Non-Goals**：接外部取消政策 API；自动取消；deadline 进状态机；过期补记；Gmail OAuth。

## Decisions

### D1. `free_cancel_deadline` 用独立 DATE 列
与 `service_date` 同构（Date, nullable, index）。进 WHERE 的日期查询（如「今天截止的条目」）需要索引；不塞 JSON（`probe_plan` 是渠道回调语义）。与 11-12 `service_date` D1 决策一致。

### D2. 截止提醒用纯函数扫描 + 事件流，不做常驻定时任务
计划内扫描（如行程详情加载 / bookings 读取时被动触发，或行前 Tab 打开时）产出 `booking.cancel_deadline` 事件，复用既有通知链路（WS feed / 未读红点）。不新增常驻 cron（运维成本与「轻量」定位冲突）。幂等靠「事件 payload 指纹」或「同条目同窗口已提醒」标记。

**核验发现（2026-11-20）**：`EVENT_TYPES`（`event_service.py:27-30`）只含 9 个类型（revise/check/skip/delay/comment/vote/edit/share/chat_edit），`booking.confirmed`/`booking.cancelled` 虽在 booking_service 里 record 但未注册（`record_event` 对未知类型只 warning 仍记录，L50-51）——本 change 把 `booking.cancel_deadline`（及顺带 `booking.confirmed`/`booking.cancelled`）一起注册进 `EVENT_TYPES`，消除 warning 历史债（与 10-28 chat_edit 同款先例）。

### D3. 提醒窗口 `(today, today+3]`
阈值常量 `CANCEL_DEADLINE_REMIND_DAYS=3`：今天不算（当天是最后一天，标「今天最后」但不进提醒事件），+1/+2/+3 触发。已截止（≤ today）绝不产出（不补记）。

### D4. 前端只读透出，不新增独立端点
台账响应已含 `days_until`，顺带加 `cancel_deadline_days`；前端「以预订条款为准」口径文案。不单独做提醒设置 UI（MVP 默认 3 天阈值，设置页超出范围）。