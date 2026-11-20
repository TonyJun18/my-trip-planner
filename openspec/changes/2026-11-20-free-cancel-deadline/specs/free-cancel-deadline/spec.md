# free-cancel-deadline Specification

## Purpose

给预订条目补上「免费取消截止日」维度：用户回填确认单时录入截止日，台账展示距离截止的倒计时，
截止前 3 天在行程内事件流给出确定性提醒。零凭证、零 LLM、绝不编造——没有截止日就没有提醒。

## ADDED Requirements

### Requirement: 预订条目携带免费取消截止日

`TripBooking` SHALL 支持可选 `free_cancel_deadline`（DATE，nullable，索引）；创建（POST /bookings）、
状态更新（POST /bookings/{id}/status）与归并（merge-email）请求 SHALL 接受该可选字段，响应 SHALL 原样返回。
该字段 SHALL NOT 参与状态机判定——条目的合法性（confirmed 必须带凭证）与截止日无关；
`free_cancel_deadline` 晚于当天 SHALL 视为「尚未截止」，早于或等于当天 SHALL 视为「已截止」。

#### Scenario: 录入免费取消截止日

- **WHEN** owner 创建一条预订：kind=hotel、status=pending、free_cancel_deadline=2026-12-01
- **THEN** 响应含 `free_cancel_deadline="2026-12-01"`
- **AND** 请求成功，无需其他字段（pending 语义不变）

#### Scenario: 省略截止日零破坏

- **WHEN** 以旧客户端字段集（无 free_cancel_deadline）创建或更新预订
- **THEN** 请求成功，响应中该字段为 null，既有行为（状态机/幂等/事件）不变

### Requirement: 台账倒计时展示截止日

预订列表与详情响应 SHALL 携带 `cancel_deadline_days`：距 `free_cancel_deadline` 的天数（未来为正、
当天为 0、已过为负），无截止日时为 `null`。倒计时 SHALL 在服务层计算（响应构造时，与 `days_until` 同源口径）。

#### Scenario: 截止日倒计时

- **WHEN** 一条预订 free_cancel_deadline=今天+3 天，另一条无截止日
- **THEN** 第一条 `cancel_deadline_days=3`，第二条 `cancel_deadline_days=null`

### Requirement: 截止前确定性提醒

系统 SHALL 提供截止前提醒扫描（纯函数 `scan_cancel_deadline_reminders(trip, bookings, today)`）：
对 `status in (pending, confirmed)` 且 `free_cancel_deadline` 落在 `(today, today+3]` 窗口的条目，
SHALL 产出提醒事件（`booking.cancel_deadline`，进 `event_service`/`trip_events`）。
已截止（deadline ≤ today）与无截止日条目 SHALL NOT 产出任何提醒；重复扫描 SHALL 幂等
（同一条目同一窗口只产出一条事件，用事件 payload 指纹去重或「已提醒」标记）。

#### Scenario: 截止前 3 天提醒

- **WHEN** 某 pending 酒店条目 free_cancel_deadline=今天+2 天
- **THEN** 扫描产出 1 条 `booking.cancel_deadline` 事件，payload 含条目 title、截止日、剩余天数
- **AND** 再次扫描同一窗口不产生第二条（幂等）

#### Scenario: 过期与缺失均不提醒

- **WHEN** 某 confirmed 条目 free_cancel_deadline=昨天（已截止）；另一条无截止日
- **THEN** 扫描不产出任何提醒（不补记过期、不编造截止日）

### Requirement: 前端截止倒计时透出

行程详情页预订台账 SHALL 展示每条预订的免费取消截止倒计时（徽标：`cancel_deadline_days` 正/零/负三态文案），
并附「以预订条款为准」口径（`basis=rule_based` 诚实标注）；无截止日的条目不渲染倒计时。
截止前 3 天的条目标记为醒目态（如琥珀色）。

#### Scenario: 台账徽标三态

- **WHEN** 台账含三条预订：A 截止日=+3 天、B 截止日=0 天、C 无截止日
- **THEN** A 显示「3 天后可免费取消」、B 显示「今天最后免费取消」、C 不渲染倒计时

