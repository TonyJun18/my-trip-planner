# Tasks — booking-ledger-rhythm

> TDD 执行顺序：每个实现任务先写失败测试（Red），再最小实现（Green）。验证命令见各任务。

## 1. 数据模型与迁移（service_date / service_note）

- [ ] 1.1 **失败测试** `backend/tests/test_booking_ledger.py::test_booking_service_date_roundtrip`：`BookingIn` 带 `service_date="2026-12-01"` 与 `service_note="G39 二等座"` 创建预订 → `BookingOut` 响应含两字段；省略两字段创建成功且为 None（旧契约零破坏）。运行 `cd backend && uv run pytest tests/test_booking_ledger.py -x` 确认 Red（字段不存在）
- [ ] 1.2 Alembic 迁移：`trip_bookings` 加 `service_date DATE NULL`（索引）+ `service_note VARCHAR(500) NULL`；`models/trip.py` TripBooking 补两列；`schemas/booking.py` BookingIn/BookingOut/BookingStatusIn 补可选字段（status 更新也接受 service_date 修正）。运行 1.1 命令确认 Green；`cd backend && uv run alembic upgrade head` 成功
- [ ] 1.3 专项回归：`uv run pytest tests/test_booking_service.py tests/test_booking_ledger.py -q` 全绿（状态机与幂等零回归）

## 2. 邮件归并端点（merge-email）

- [ ] 2.1 **失败测试**（append 1.1 文件）：`POST /trips/{id}/bookings/merge-email` owner 归并一条有码酒店条目（code=BK12345678）→ 台账出现 pending + reference=email.import 条目；重复归并同一 code → 仍一条（幂等）；无码航班条目归并两次 → order_no 均为 `em-` 前缀合成键且只一条；归并条目请求置 confirmed 无凭证 → 400 booking_invalid_transition；非 owner（他人 token）→ 404。运行确认 Red
- [ ] 2.2 最小实现：`schemas/booking.py` 加 `EmailMergeIn`（kind/name/code/datetime/amount/currency/fingerprint 可选）+ `reference` Literal 扩 `email.import`；`booking_service.merge_email_bookings`（有码走既有 upsert 幂等；无码合成 `em-sha1(kind|name|datetime|amount)[:16]` 填 order_no，强制 status=pending、忽略请求侧 status/credential 注入）；`trips_bookings.py` 挂端点（`/scan` 旁，owner 校验复用 `get_trip`）。运行 2.1 确认 Green
- [ ] 2.3 专项回归：`uv run pytest tests/test_booking_ledger.py tests/test_email_import.py -q` 全绿（解析层零改动、归并层新增覆盖）

## 3. 台账排序/倒计时 + 导出补预订（脱敏）

- [ ] 3.1 **失败测试**（append）：三条预订（A=3 天后 / B=1 天后 / C 无日期）→ `GET /bookings` 顺序 B、A、C，B 的 `days_until=1`、C 为 null；导出两路径——owner 导出 JSON bookings 段含 credential 原值，share 令牌导出 bookings 段**无** credential 键、order_no 匹配 `^\*{4}\d{4}$`（`em-` 键为 "—"）。运行确认 Red
- [ ] 3.2 最小实现：`booking_service.list_bookings` 排序改 `service_date.asc().nulls_last(), created_at.asc()`；`BookingOut` 加 `days_until`（响应构造时算日期差，查询当日用本地时区日期）；`export_service.build_trip_export` 加 bookings 段 + `_sanitize_booking`（share 路径：剔 credential、order_no 尾 4 掩码）单处集中。运行 3.1 确认 Green
- [ ] 3.3 后端全套回归：`cd backend && uv run pytest -q` 既有 453+ 测试零失败

## 4. 预订节奏规则库（booking_rhythm）

- [ ] 4.1 **失败测试** `backend/tests/test_booking_rhythm.py`：纯函数 `compute_booking_rhythm(trip, bookings, today)`——火车 15 天预售窗口（service_date=2026-12-01 → window_open=2026-11-16，phase 按 today 三分支 open/upcoming）；「故宫」站命中放票表（提前 7 天）+ 未命中 timed-entry 站走通用档（不编造具体时刻）；机票目标输出关注窗口（无价格断言）；酒店条目入住前 7 天取消检查；已 confirmed 目标去重（不产出）、pending 保留；同一目标至多一条；每次调用结果一致且不产生 trip_events 记录；全部条目 basis=rule_based + 「以官方渠道为准」提示。运行确认 Red
- [ ] 4.2 最小实现：新建 `backend/app/services/booking_rhythm.py`（规则常量表集中 + datetime 日期数学，零网络零 LLM）；`trips_bookings.py` 挂 `GET /trips/{id}/bookings/rhythm`（owner）。运行 4.1 确认 Green
- [ ] 4.3 专项回归：`uv run pytest tests/test_booking_rhythm.py tests/test_booking_ledger.py -q` 全绿

## 5. 前端：台账面板 / 邮件归并入口 / 日卡片徽标

- [ ] 5.1 i18n：`zh-CN.js`/`en-US.js` booking 组补键（约 12 键：分组标题待办/已确认/已取消、daysUntil、daysAgo、mergeToLedger、merged、rhythmTitle、rhythmOpen/Upcoming/Closing、basisNote 官方提示等），`grep` 键数 zh=en；`cd frontend && npm run check:i18n` 通过
- [ ] 5.2 `api/modules/bookings.js`：补 `mergeEmailBookings(tripId, items)` 与 `getBookingRhythm(tripId)` 封装；`ImportDialog.vue` 邮件 Tab 结果区新增「并入台账」按钮（勾选条目 → 调归并 → 成功提示 + 可选跳转行前 Tab）。验证：`cd frontend && npm run build` 通过
- [ ] 5.3 `BookingPanel.vue` 升级：按 `days_until`/service_date 排序渲染、三状态分组小标题、倒计时徽标（正/零/负三种文案）、pending 条目 hint「确认需回填真实凭证」。验证：build 通过 + 手动检查面板渲染（含空态）
- [ ] 5.4 `TripDetailDayCard.vue`：日卡片按 service_date==day.date 过滤 confirmed 条目渲染订单徽标（kind 图标 + provider 标签；无命中不渲染；pending/cancelled 不显示）。验证：build 通过
- [ ] 5.5 行前 Tab 节奏卡：BookingPanel 上方（或并列）渲染 rhythm 条目列表（phase 徽标 open=可订/closing=临近截止/upcoming=未开 + window 日期 + basis 官方提示）。验证：build 通过

## 6. 端到端验证（真机）

- [ ] 6.1 后端重启（最新代码）+ 前端 dev：粘贴一封含确认码的酒店确认邮件 → ImportDialog 识别 → 「并入台账」→ 行前 Tab 出现 pending 条目（reference=email.import）→ 回填凭证升 confirmed → 对应日卡片出现订单徽标；截图留档 `/tmp/booking-ledger-*.png`
- [ ] 6.2 打开含故宫/热门场馆的行程 → 行前 Tab 节奏卡出现放票窗口条目（window_open=游玩日-7、basis=rule_based）；已确认目标不出现在节奏卡
- [ ] 6.3 导出核验：owner 导出 JSON 含 bookings 段（credential 原值）；分享令牌导出无 credential 键、order_no 已掩码

## Workflow follow-up（归档相关，非 tracked）

- 全部 tracked 任务完成且验证证据齐全后：`openspec archive booking-ledger-rhythm`
- 归档后按需更新 `README.md`「中立立场」小节（预订台账一句话：凭证只在 owner 侧全量，分享侧脱敏）与 `docs/night-build-todo.md` 登记完成项
- 方案三（同行人只读已订视图 + ICS 预订条目 + probe_plan 结构化订单）另立 change，不在本范围
