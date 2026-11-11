# 实现计划：booking-ledger-rhythm（OTA 预订管理 · 台账 + 节奏）

- 日期：2026-11-11
- 工作流：openspec-superpowers-workflow（OpenSpec artifacts 已完成并校验通过，本计划为 Superpowers 执行交接件）
- OpenSpec change：`openspec/changes/booking-ledger-rhythm/`（proposal / design / specs×2 / tasks）
- Spec 权威：行为冲突以 specs 为准（booking-ledger / booking-rhythm），本计划为其任务分解
- 基线：worktree `/Users/pengjun/Documents/my-agent/.worktrees/booking-ledger-rhythm`，分支 `nightly/2026-11-11/0-booking-ledger-rhythm`（main c731e51），基线测试 **997 passed / 1 skipped**（命令 `cd backend && uv run python -m pytest -q`）
- 全局约束：中立立场（零库存/零资金/零返佣）；confirmed 凭证防线不放松；`basis=rule_based` 诚实标注；不触碰主 checkout 未提交的 schedule-timeline 工作
- 测试命令统一用 `uv run python -m pytest`（`uv run pytest` 在本环境不解析 `app` 包，见 ledger Ruling）

## Task 1: 数据模型与迁移（service_date / service_note）

**RED**：新建 `backend/tests/test_booking_ledger.py`：
- `test_booking_service_date_roundtrip`：POST /api/v1/trips/{id}/bookings 带 `service_date="2026-12-01"` 与 `service_note="G39 二等座"`（status=pending）→ 200，响应 JSON 含两字段原值
- `test_booking_optional_fields_default_none`：不带两字段创建 → 200，响应两字段为 None
- `test_booking_status_update_service_date`：PATCH 路径 `POST /{booking_id}/status` 带 service_date 修正 → 响应更新
运行 `cd backend && uv run python -m pytest tests/test_booking_ledger.py -x -q`。
**Expected: 失败**（AssertionError/字段缺失——service_date 尚不存在，422 或 KeyError）。

**GREEN**：
1. `models/trip.py` TripBooking 加 `service_date: Mapped[date | None]`（Date, nullable, index=True）与 `service_note: Mapped[str | None]`（String(500)）
2. Alembic 迁移一枚（upgrade 加两列 + service_date 索引；downgrade 可回）
3. `schemas/booking.py`：BookingIn/BookingOut 加 `service_date: date | None = None`、`service_note: str | None = Field(default=None, max_length=500)`；BookingStatusIn 加同名字段；`booking_service.update_booking_status` 透传 service_date/service_note
运行同上命令。**Expected: 通过**；再跑 `uv run python -m pytest tests/test_booking_service.py tests/test_booking_ledger.py -q` **Expected: 全绿**；`uv run alembic upgrade head` 成功。
提交：`feat(booking): TripBooking 增 service_date/service_note（schema+迁移+状态更新透传）`

## Task 2: 邮件归并端点（merge-email）

**RED**（append `test_booking_ledger.py`）：
- `test_merge_email_with_code_idempotent`：归并酒店条目（provider=ctrip、code=BK12345678）两次 → 台账一条 pending、reference=email.import；第二次返回同一 id
- `test_merge_email_without_code_fingerprint_key`：无码航班条目归并两次 → order_no 均 `em-` 前缀、仅一条
- `test_merge_email_confirmed_requires_credential`：归并条目 POST status=confirmed 无凭证 → 400 booking_invalid_transition
- `test_merge_email_owner_isolated`：他人 token → 404
- `test_merge_email_ignores_client_status_injection`：请求带 status=confirmed+credential → 落库仍 pending、reference=email.import（合成键条目）；有码条目允许落 pending 不自动 confirmed
运行确认 **Expected: 失败**（404 端点不存在）。

**GREEN**：
1. `schemas/booking.py` 加 `EmailMergeIn`（kind/title/name/code/order_no/datetime/amount/currency/fingerprint；全部可选带默认）；`schemas/__init__.py` 导出
2. `schemas/booking.py` reference Literal 扩 `"email.import"`（BookingIn）
3. `booking_service.merge_email_bookings(db, trip_id, items, *, owner)`：有码→构造 BookingIn(provider 映射 ctrip 默认、order_no=code、status="pending"、reference="email.import") 复用 `upsert_booking`；无码→order_no=f"em-{sha1(kind|name|datetime|amount)[:16]}"，同上；强制 status=pending（忽略请求侧 status/credential），服务端绝不信解析结果
4. `trips_bookings.py` 挂 `POST /{trip_id}/bookings/merge-email`（body: `{items: [...]}`，owner 校验走 get_trip）
运行确认 **Expected: 通过**；回归 `uv run python -m pytest tests/test_booking_ledger.py tests/test_email_import.py -q` **Expected: 全绿**。
提交：`feat(booking): 邮件导入一键归并台账（幂等 em- 合成键 + pending + reference=email.import）`

## Task 3: 台账排序/倒计时 + 导出补预订（脱敏）

**RED**（append）：
- `test_list_bookings_sorted_by_service_date`：造 A(+3d)/B(+1d)/C(None) 三条 → GET /bookings 顺序 [B, A, C]（id 序断言）；B 的 `days_until=1`（用 freezegun 或以 today 相对构造日期）、C 的 `days_until=None`
- `test_export_owner_contains_bookings_full`：owner 导出 JSON bookings 段含 credential 原值与 order_no
- `test_export_share_masks_bookings`：share 令牌导出 bookings 段：每条无 `credential` 键、order_no 匹配 `^\*{4}\d{4}$`、`em-` 键输出为 "—"
运行确认 **Expected: 失败**（顺序错/无 bookings 段/无 days_until）。

**GREEN**：
1. `booking_service.list_bookings`：order_by `service_date.asc().nulls_last(), created_at.asc()`
2. `BookingOut.days_until`（`int | None`，非 ORM 字段，response 构造时计算——在 API 层把 ORM 转 Out 时注入 `_days_until`，date 差基于本地 today）
3. `export_service.build_trip_export`：bookings 段 + `_sanitize_booking(b, *, full: bool)` 单处集中（full=True owner；False → 剔 credential、order_no 尾 4 掩码、`em-` 前缀 → "—"）；share 路径传 full=False
运行确认 **Expected: 通过**；全套回归 `uv run python -m pytest -q` **Expected: 997+ 新增全绿 0 failed**。
提交：`feat(booking): 台账排序/倒计时 + 导出含预订（share 路径凭证脱敏）`

## Task 4: 预订节奏规则库（booking_rhythm）

**RED**：新建 `backend/tests/test_booking_rhythm.py`（纯函数 `compute_booking_rhythm(trip, bookings, today)`）：
- 火车预售：suggested/pending 火车票 service_date=2026-12-01 → window_open=2026-11-16；today=2026-11-10 → phase=upcoming；today=2026-11-16 → open
- 故宫放票：站点名含「故宫」→ ticket 条目 window_open=游玩日-7；未命中表但 timed-entry 命中 → 通用档（提前 7 天，note 不含具体放票时刻）
- 机票：service_date 未来 → 关注窗口条目（无价格断言字段）
- 酒店：入住日-7 取消检查提醒
- 去重：已 confirmed 火车票 → 不产出该目标；pending → 保留；同一 (kind, service_date/stop) 至多一条
- 无副作用：调用两次结果相等，且 trip_events 无新增（service 层不发事件）
- 每条 basis="rule_based" 且 note 含「以官方渠道为准」
运行确认 **Expected: 失败**（模块不存在）。

**GREEN**：新建 `services/booking_rhythm.py`（规则常量表 `_TRAIN_PRESALE_DAYS=15`、`_VENUE_RELEASE_DAYS={"故宫":7,...}` 复用 booking_service._TIMED_ENTRY_KEYWORDS、`_FLIGHT_WATCH_DAYS=30`、`_HOTEL_CANCEL_CHECK_DAYS=7`；纯日期数学）；`trips_bookings.py` 挂 `GET /{trip_id}/bookings/rhythm`（owner）。
运行确认 **Expected: 通过**；回归 `uv run python -m pytest tests/test_booking_rhythm.py tests/test_booking_ledger.py -q` **Expected: 全绿**。
提交：`feat(booking): 确定性预订节奏规则库（预售/放票/关注窗口/取消检查，basis=rule_based）`

## Task 5: 前端（台账面板 / 归并入口 / 日卡片徽标 / 节奏卡）

步骤（每步验证 `cd frontend && npm run build` 通过）：
1. i18n：`zh-CN.js`/`en-US.js` booking 组补约 12 键（groupTodo/groupConfirmed/groupCancelled/daysUntil(+1 天后)/daysAgo/mergeToLedger/mergedOk/rhythmTitle/phaseOpen/phaseUpcoming/phaseClosing/rhythmBasisNote）；`npm run check:i18n` **Expected: 无缺失无重复**
2. `api/modules/bookings.js`：`mergeEmailBookings(tripId, items)`、`getBookingRhythm(tripId)` 封装
3. `ImportDialog.vue` 邮件 Tab 结果区：条目勾选 + 「并入台账」按钮 → 调 mergeEmailBookings（当前行程）→ 成功 ElMessage + emit 刷新
4. `BookingPanel.vue`：列表按 service_date 排序（后端已排序，前端保序渲染）、三状态分组标题、倒计时徽标（days_until>0「N 天后」/0「今天」/<0「N 天前」/null 不显示）、pending hint「确认需回填真实凭证」；节奏卡（panel 上方）：rhythm 条目 phase 徽标 + window 日期 + basis 提示
5. `TripDetailDayCard.vue`：props 增 confirmedBookings（父组件从 GET /bookings 过滤 service_date==day.date 且 status=confirmed 传入），渲染订单徽标（kind 图标 + provider 标签；空数组不渲染）
提交：`feat(frontend): 预订台账面板/邮件归并入口/日卡片订单徽标/节奏卡`

## Task 6: 端到端验证（真机）

1. 启动后端（worktree 代码）+ 前端 dev：粘贴含确认码的酒店确认邮件 → 识别 → 并入台账 → 行前 Tab pending 条目（reference=email.import）→ 回填凭证升 confirmed → 对应日卡片订单徽标；截图 `/tmp/booking-ledger-*.png`
2. 含故宫行程 → 节奏卡放票窗口条目（window_open=游玩日-7、basis=rule_based）；已确认目标不出现
3. 导出核验：owner JSON bookings 段含 credential；share 导出无 credential、order_no 已掩码
**Expected: 三条链路全部可操作且证据齐全**；后端全套回归最后一次 `uv run python -m pytest -q` 全绿。
提交：`chore(nightly): booking-ledger-rhythm 端到端验证证据登记`

## Workflow follow-up（非 tracked）

- 完成后：`openspec archive booking-ledger-rhythm`（在 worktree）
- README「中立立场」小节补一句 + `docs/night-build-todo.md` 登记完成项
- 主 checkout 的 schedule-timeline 未提交工作与本分支将合并时 TripDetailDayCard.vue 可能冲突，合并时人工调和
