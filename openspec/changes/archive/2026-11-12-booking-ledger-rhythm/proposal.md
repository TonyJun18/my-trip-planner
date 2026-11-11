# Proposal

## Why

预订状态机、外链与凭证回填已具备（task-booking-outlink / task-book-ahead-scan），但「管理」停留在列表陈列：邮件导入解析出的预订条目是断头路（只回显候选、不归并台账，`email_import.py` 无 upsert 调用）；`TripBooking` 没有服务日期字段（火车哪天开、酒店哪天入住都不存，`models/trip.py:313-347`），无法排序、倒计时、按日投影；导出不含预订（`export_service.py` grep `booking` 零命中，「数据自由」在预订维度缺一角）；前瞻扫描只有「该不该订」没有「什么时候订」（12306 预售期、热门场馆放票日等时间规则缺失）。竞品实证（Tineo / TripIt post-booking organization、Wanderlog 预订邮件导入、Expedia Property Expert「答案跟随预订」）：**订后整理是 2026 独立规划层与巨头的共同战场**，而我们台账底座已备、只差管理纵深。本 change 不碰已两次评估关单的预订闭环立场（10-28 booking-closure / 11-08 booking-neutrality：零库存、零资金、零返佣不变）。

## What Changes

- `TripBooking` 新增可选 `service_date`（服务日期：发车日 / 入住日 / 出行日）与可选 `service_note`（用户备注：车次 / 房型 / 取消政策，自由文本零结构化承诺），一次 Alembic 迁移；`BookingIn` / `BookingOut` 同步补字段，全部可选零破坏。
- 邮件导入结果一键「并入台账」：新增 `POST /trips/{trip_id}/bookings/merge-email`，复用幂等 upsert（`provider+order_no`），条目以 `status=pending`、`reference=email.import` 落台账（parsed code 缺失时允许 pending 无凭证——pending 语义本就是「订了待确认」；升 confirmed 仍必须带凭证，状态机防线不放松）。
- 台账读取升级：`GET /trips/{id}/bookings` 响应按 `service_date` 排序（空值排末尾，创建时间次序兜底），新增 `days_until`（距服务日期天数，含 null）。
- `BookingPanel.vue` 升级为订单台账：状态分组（待办/已确认/已取消）、按日期排序与倒计时徽标、邮件归并入口（ImportDialog 邮件 Tab 结果区新增「并入台账」动作）。
- 已确认预订投影到日程：详情页日卡片对当天有 `confirmed` 预订（service_date 命中）的站点行追加订单徽标（kind 图标 + provider 标签），读取 `GET /trips/{id}/bookings` 一次性拉取、前端本地按日期匹配，零后端新端点。
- 导出补预订：`build_trip_export` 增 `bookings` 段（owner 路径全量；share 令牌路径脱敏——`order_no` 仅保留尾 4 位、`credential` 永不输出）。
- 新增确定性预订节奏规则库 `booking_rhythm.py`（纯函数、零凭证、零 LLM、`basis=rule_based` 诚实标注）：12306 火车 15 天预售窗口、热门场馆放票日规则（故宫 7 天等，复用 `scan_bookable_stops` 关键词表）、国内机票价格曲线启发式（T-30 前后建议关注）、酒店取消政策检查提醒（入住前 7 天）。产出挂 `GET /trips/{id}/bookings/rhythm`：按日期输出「窗口已开 / 窗口未开 / 即将截止」三类节奏条目，与前瞻扫描建议合并透出。
- **不做**（显式边界）：分销/联盟 API、代收资金、伪造「已订」、联盟参数、自动比价聚合（10-28 / 11-08 两次评估已关单，本 change 全部维持）。

## Capabilities

### New Capabilities

- `booking-ledger`: 行前订单台账——预订条目的服务日期与备注字段、邮件导入结果归并（幂等、pending 落库、confirmed 凭证防线不变）、台账排序与倒计时、确认预订投影到日卡片、导出含预订（分享路径脱敏契约）。
- `booking-rhythm`: 预订节奏规则库——确定性「什么时候该订什么」：预售/放票/价格曲线/取消检查四类时间规则的窗口计算、与前瞻扫描建议的合并契约、`basis=rule_based` 诚实标注与不编造边界。

### Modified Capabilities

<!-- 无：既有 specs 仅 favorite-spots，与本 change 无需求级交集 -->

## Impact

- **后端**：`backend/app/models/trip.py`（TripBooking 两列）+ `alembic` 迁移一枚；`backend/app/schemas/booking.py`（BookingIn/BookingOut/BookingStatusIn 增可选字段、EmailMergeIn 新模型）；`backend/app/services/booking_service.py`（排序/倒计时/邮件归并/投影辅助）；新建 `backend/app/services/booking_rhythm.py`；`backend/app/api/v1/trips_bookings.py`（merge-email、rhythm 两端点 + 列表排序）；`backend/app/services/export_service.py`（bookings 段 + 脱敏）。
- **前端**：`BookingPanel.vue`（分组/倒计时/排序）、`ImportDialog.vue`（邮件 Tab「并入台账」动作 + api 封装）、`TripDetailDayCard.vue`（订单徽标）；i18n zh/en 约 10-14 键。
- **零破坏**：既有状态机与凭证防线不放松；`channel.callback` reference 语义不动；453+ 既有测试应零回归（BookingOut 新增字段全部可选）。
- **依赖**：零新依赖（规则库纯日期数学，datetime 标准库）。
